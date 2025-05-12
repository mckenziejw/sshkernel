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

    def _ensure_clean_prompt(self):
        """Ensure we're at a clean prompt by clearing the line and sending a newline"""
        self._shell_channel.send('\x15\n')  # Ctrl+U + newline
        return self._read_until_prompt()

    def exec_command(self, cmd, print_function):
        """Execute command and stream output"""
        if not self.isconnected():
            raise Exception("Not connected")

        # Clean the command
        cmd = cmd.strip()
        print_function(f"[ssh] Sending command: {cmd}\n")
        
        # Send command with a newline
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
            
            # Check for error messages
            error_patterns = [
                r"^\s*error:",
                r"^\s*unknown command\.",
                r"^\s*syntax error\.",
                r"^\s*invalid command\."
            ]
            
            has_error = False
            for line in lines:
                if any(re.search(pattern, line.lower()) for pattern in error_patterns):
                    has_error = True
                print_function(line + '\n')
            
            # Ensure we're at a clean prompt after command execution
            self._ensure_clean_prompt()
            
            return 1 if has_error else 0
            
        except TimeoutError as e:
            print_function(f"[ssh] Error: {str(e)}\n")
            # Ensure clean prompt on error
            self._ensure_clean_prompt()
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

    def _get_completions_cli_command(self, partial_cmd):
        """Get completions using 'show cli complete-on' command"""
        try:
            # Send completion command without quotes
            completion_cmd = f'show cli complete-on "{partial_cmd}"'
            print(f"[DEBUG] Trying CLI completion with command: {completion_cmd}")
            self._shell_channel.send(completion_cmd + '\n')
            
            output = self._read_until_prompt()
            print(f"[DEBUG] CLI completion output:\n{output}")
            lines = output.split('\n')
            completions = []
            
            # Skip the first line (echo of our command) and last line (prompt)
            for line in lines[1:-1]:
                if not line.strip() or line.strip() == "Possible completions:":
                    continue
                    
                # Split on first whitespace sequence
                parts = line.strip().split(None, 1)
                if parts:
                    word = parts[0]
                    # Only add if it's a valid completion (not a parameter hint)
                    if not word.startswith('<') and not word.endswith('>'):
                        completions.append(word)
            
            # Ensure we're at a clean prompt
            self._ensure_clean_prompt()
            
            print(f"[DEBUG] CLI completions found: {completions}")
            # If we got completions and no error message, return them
            if completions and not any("error: unknown command" in line.lower() for line in lines):
                return completions
            
            return None  # Signal to try fallback method
            
        except Exception as e:
            print(f"[DEBUG] CLI completion error: {str(e)}")
            self._ensure_clean_prompt()  # Always ensure clean prompt on error
            return None  # Signal to try fallback method

    def _get_completions_question_mark(self, partial_cmd):
        """Get completions using question mark method"""
        try:
            # First ensure we're at a clean prompt
            self._ensure_clean_prompt()
            
            # Send the partial command with ?
            print(f"[DEBUG] Trying ? completion with: {partial_cmd}?")
            self._shell_channel.send(partial_cmd + '?\n')
            
            # Read the completion suggestions
            output = self._read_until_prompt()
            print(f"[DEBUG] ? completion output:\n{output}")
            
            # Parse the completion output
            lines = output.split('\n')
            completions = []
            
            # Skip the first line (echo of our command) and last line (prompt)
            for line in lines[1:-1]:
                if not line.strip() or line.strip() == "Possible completions:":
                    continue
                
                # Split on whitespace and take first word, handling descriptions
                parts = line.strip().split(None, 1)
                if parts:
                    word = parts[0].strip()
                    # Only add if it's a valid completion (not a parameter hint)
                    if not word.startswith('<') and not word.endswith('>'):
                        # Remove any trailing characters that might have been added
                        word = word.rstrip('?')
                        completions.append(word)
            
            # Clear any remaining ? and buffer
            self._shell_channel.send('\x15\n')  # Ctrl+U + newline to clear line
            self._read_until_prompt()
            self._shell_channel.send('\n')  # Extra newline to ensure clean state
            self._read_until_prompt()
            
            print(f"[DEBUG] ? completions found: {completions}")
            return completions
            
        except Exception as e:
            print(f"[DEBUG] ? completion error: {str(e)}")
            # Ensure we clean up even on error
            self._shell_channel.send('\x15\n')  # Ctrl+U + newline
            self._read_until_prompt()
            self._shell_channel.send('\n')  # Extra newline
            self._read_until_prompt()
            return []

    def _get_completions(self, partial_cmd):
        """Get completion suggestions for a partial command"""
        # Try question mark method first since it's more widely supported
        completions = self._get_completions_question_mark(partial_cmd)
        
        # Only if question mark method fails or returns no results, try CLI command method
        if not completions:
            completions = self._get_completions_cli_command(partial_cmd)
            if completions is None:
                completions = []
        
        return completions

    def get_completions(self, text):
        """Get completion suggestions for the current text"""
        try:
            if not text.strip():
                return []
                
            print(f"[DEBUG] Getting completions for: {text}")
            # Clean the input text
            text = text.strip()
            
            # Send the completion request
            completions = self._get_completions(text)
            
            # Filter completions that match our text and clean them
            matches = []
            for comp in completions:
                comp = comp.strip()
                if comp.startswith(text):
                    matches.append(comp)
            
            print(f"[DEBUG] Final filtered matches: {matches}")
            
            # Sort and remove duplicates while preserving case
            return sorted(list(set(matches)), key=str.lower)
            
        except Exception as e:
            print(f"[DEBUG] Completion error: {str(e)}")
            # If anything goes wrong, return empty list
            return [] 