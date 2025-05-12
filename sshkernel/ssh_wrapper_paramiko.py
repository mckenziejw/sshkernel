import os
import re
import time
import paramiko
from paramiko import SSHException
from .ssh_wrapper import SSHWrapper

class SSHWrapperParamiko(SSHWrapper):
    """
    A direct Paramiko SSH client wrapper.
    SSHWrapperParamiko wraps ssh client without requiring bash shell.
    """

    def __init__(self, envdelta_init=dict()):
        self.envdelta_init = envdelta_init
        self._client = None
        self._channel = None
        self.__connected = False
        self._host = ""
        self._cwd = None
        self._env = {}
        self._shell_channel = None
        self._shell_buffer = ""

    def connect(self, host):
        """Connect to remote host using SSH config"""
        if self._client:
            self.close()

        self._client = paramiko.SSHClient()
        self._client.load_system_host_keys()
        self._client.set_missing_host_key_policy(paramiko.WarningPolicy())

        # Parse SSH config
        ssh_config = paramiko.SSHConfig()
        user_config_file = os.path.expanduser("~/.ssh/config")
        if os.path.exists(user_config_file):
            with open(user_config_file) as f:
                ssh_config.parse(f)

        # Extract username from host if present (user@host format)
        username_from_host = None
        m = re.search("([^@]+)@(.*)", host)
        if m:
            username_from_host = m.group(1)
            host = m.group(2)

        # Get host config
        cfg = ssh_config.lookup(host)
        
        # Build connection parameters
        hostname = cfg.get('hostname', host)
        username = username_from_host or cfg.get('user')
        port = int(cfg.get('port', 22))
        key_filename = cfg.get('identityfile', None)
        if isinstance(key_filename, list):
            key_filename = key_filename[0]

        # Connect
        self._client.connect(
            hostname=hostname,
            username=username,
            port=port,
            key_filename=key_filename,
        )

        self.__connected = True
        self._host = host
        
        # Initialize environment
        self._env.update(self.envdelta_init)
        self._env['PAGER'] = 'cat'  # Prevent paging

        # Set up interactive shell
        self._shell_channel = self._client.invoke_shell()
        # Wait for initial prompt
        time.sleep(2)
        self._read_until_prompt()

        # Configure Junos CLI settings
        self._shell_channel.send('set cli complete-on-space off\n')
        self._read_until_prompt()
        self._shell_channel.send('set cli screen-length 0\n')
        self._read_until_prompt()
        
        # Also send a newline to ensure we have a clean prompt
        self._shell_channel.send('\n')
        self._read_until_prompt()

    def _read_until_prompt(self, timeout=30):
        """Read from shell until a prompt is found"""
        buffer = ""
        start_time = time.time()
        
        while True:
            if self._shell_channel.recv_ready():
                chunk = self._shell_channel.recv(4096).decode('utf-8', errors='replace')
                buffer += chunk
                
                # Check for "More" prompt and handle it
                if buffer.endswith('---(more)---'):
                    self._shell_channel.send(' ')  # Send space to show more
                    buffer = buffer[:-12]  # Remove the (more) prompt
                    continue
                elif buffer.endswith('---(more 100%)---'):
                    self._shell_channel.send(' ')  # Send space to continue
                    buffer = buffer[:-17]  # Remove the (more 100%) prompt
                    continue
                
                # Check for various Junos prompts:
                # - Operational mode: user@host>
                # - Configuration mode: user@host#
                # - Configuration mode with hierarchy: [edit interfaces ge-0/0/0]user@host#
                # - Loading/error states: {master:0}user@host%
                if re.search(r'(?:\{master:\d+\})?(?:\[edit[^\]]*\])?[a-zA-Z0-9\-_]+@[a-zA-Z0-9\-_]+[%>#]\s*$', buffer):
                    return buffer
                
            if time.time() - start_time > timeout:
                # Include the buffer in the timeout error to help debugging
                raise TimeoutError(f"Timeout waiting for prompt. Buffer received: {buffer}")
                
            time.sleep(0.1)

    def exec_command(self, cmd, print_function):
        """Execute command and stream output"""
        if not self.isconnected():
            raise Exception("Not connected")

        print_function(f"[ssh] Sending command: {cmd}\n")
        
        # Send command
        self._shell_channel.send(cmd + '\n')
        
        try:
            # Read response
            output = self._read_until_prompt()
            
            # Remove the command echo and trailing prompt
            lines = output.split('\n')
            if lines and lines[0].strip() == cmd.strip():
                lines = lines[1:]
            if lines and re.search(r'(?:\{master:\d+\})?(?:\[edit[^\]]*\])?[a-zA-Z0-9\-_]+@[a-zA-Z0-9\-_]+[%>#]\s*$', lines[-1]):
                lines = lines[:-1]
            
            # Print output
            for line in lines:
                print_function(line + '\n')
            
            return 0  # Since we can't reliably get exit codes in this mode
            
        except TimeoutError as e:
            print_function(f"[ssh] Error: {str(e)}\n")
            return 1

    def close(self):
        """Close the SSH connection"""
        self.__connected = False
        if self._shell_channel:
            self._shell_channel.close()
        if self._client:
            self._client.close()
        self._shell_channel = None
        self._client = None

    def interrupt(self):
        """Interrupt the current command"""
        if self._shell_channel:
            # Send Ctrl+C
            self._shell_channel.send('\x03')
            time.sleep(0.1)
            # Clear any remaining output
            self._read_until_prompt()

    def isconnected(self):
        """Check if connected to remote host"""
        return self.__connected 

    def _get_completions(self, partial_cmd):
        """Get completion suggestions for a partial command"""
        # Save current buffer and send completion request
        self._shell_channel.send(partial_cmd + '?\n')
        
        # Read the completion suggestions
        output = self._read_until_prompt()
        
        # Parse the completion output
        lines = output.split('\n')
        completions = []
        
        # Skip the first line (echo of our command) and last line (prompt)
        for line in lines[1:-1]:
            # Skip empty lines
            if not line.strip():
                continue
            
            # Handle possible formats:
            # 1. Simple completion: "term    Complete word"
            # 2. Description only: "  Description of options"
            # 3. Multiple per line: "term1  term2  term3"
            parts = line.strip().split()
            if parts:
                # If line starts with spaces, it's a description
                if line.startswith('    '):
                    continue
                # Add all non-description words as completions
                completions.extend([p for p in parts if not p.startswith('<') and not p.endswith('>')])
        
        return completions

    def get_completions(self, text):
        """Get completion suggestions for the current text"""
        try:
            # Send the completion request
            completions = self._get_completions(text)
            
            # Filter completions that match our text
            matches = [c for c in completions if c.startswith(text)]
            
            # Sort and remove duplicates
            return sorted(list(set(matches)))
            
        except Exception as e:
            # If anything goes wrong, return empty list
            return [] 