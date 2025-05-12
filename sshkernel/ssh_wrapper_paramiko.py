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

    def _read_until_prompt(self, timeout=30):
        """Read from shell until a prompt is found"""
        buffer = ""
        start_time = time.time()
        
        while True:
            if self._shell_channel.recv_ready():
                chunk = self._shell_channel.recv(4096).decode('utf-8', errors='replace')
                buffer += chunk
                
                # Check for various Junos prompts
                if re.search(r'[%>#]\s*$', buffer):
                    return buffer
                
            if time.time() - start_time > timeout:
                raise TimeoutError("Timeout waiting for prompt")
                
            time.sleep(0.1)

    def exec_command(self, cmd, print_function):
        """Execute command and stream output"""
        if not self.isconnected():
            raise Exception("Not connected")

        # Send command
        self._shell_channel.send(cmd + '\n')
        
        # Read response
        output = self._read_until_prompt()
        
        # Remove the command echo and trailing prompt
        lines = output.split('\n')
        if lines and lines[0].strip() == cmd.strip():
            lines = lines[1:]
        if lines and re.search(r'[%>#]\s*$', lines[-1]):
            lines = lines[:-1]
        
        # Print output
        for line in lines:
            print_function(line + '\n')

        return 0  # Since we can't reliably get exit codes in this mode

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