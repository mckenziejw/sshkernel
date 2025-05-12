import os
import re
import time
import paramiko
from paramiko import SSHException
from .ssh_wrapper import SSHWrapper
import traceback

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
                # - Configuration mode with changes: user@host# (pending changes)
                if re.search(r'(?:\{master:\d+\})?(?:\[edit[^\]]*\])?[a-zA-Z0-9\-_]+@[a-zA-Z0-9\-_]+[%>#](?:\s+\(pending changes\))?\s*$', buffer):
                    return buffer
                
            if time.time() - start_time > timeout:
                # Include the buffer in the timeout error to help debugging
                raise TimeoutError(f"Timeout waiting for prompt. Buffer received: {buffer}")
                
            time.sleep(0.1)

    def _ensure_clean_prompt(self):
        """Ensure we're at a clean prompt by clearing the line and sending a newline"""
        self._shell_channel.send('\x15\n')  # Ctrl+U + newline
        return self._read_until_prompt()

    def test_completion(self, cmd, print_function):
        """Test completion functionality directly"""
        try:
            print_function("[DEBUG] Starting completion test")
            
            # First ensure we're at a clean prompt
            output = self._ensure_clean_prompt()
            print_function(f"[DEBUG] Current prompt:\n{output}")
            
            # Send the command with ?
            print_function(f"[DEBUG] Sending command: {cmd}?")
            self._shell_channel.send(cmd + '?\n')
            
            # Read the response
            output = self._read_until_prompt()
            print_function(f"[DEBUG] Response from device:\n{output}")
            
            # Clean up
            self._shell_channel.send('\x15\n')  # Ctrl+U + newline
            self._read_until_prompt()
            
            return True
            
        except Exception as e:
            print_function(f"[DEBUG] Test error: {str(e)}\n{traceback.format_exc()}")
            return False

    def exec_command(self, cmd, print_function):
        """Execute command and stream output"""
        if not self.isconnected():
            raise Exception("Not connected")

        # Special handling for test command
        if cmd.startswith("__test_completion"):
            test_cmd = cmd.split(" ", 1)[1] if " " in cmd else ""
            return 0 if self.test_completion(test_cmd, print_function) else 1

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

    def _get_completions_question_mark(self, partial_cmd, print_function=print):
        """Get completions using question mark method"""
        try:
            # First ensure we're at a clean prompt
            self._ensure_clean_prompt()
            
            # Send the partial command with ?
            print_function(f"[DEBUG] Trying ? completion with: {partial_cmd}?")
            self._shell_channel.send(partial_cmd + '?\n')
            
            # Read the completion suggestions
            output = self._read_until_prompt()
            print_function(f"[DEBUG] Raw ? completion output:\n{output}")
            
            # Parse the completion output
            lines = output.split('\n')
            completions = []
            
            print_function(f"[DEBUG] Processing {len(lines)} lines")
            in_completions = False
            # Skip the first line (echo of our command) and last line (prompt)
            for i, line in enumerate(lines[1:-1]):
                print_function(f"[DEBUG] Processing line {i+1}: '{line}'")
                
                # Skip empty lines
                if not line.strip():
                    print_function(f"[DEBUG] Skipping empty line")
                    continue
                
                # Check for completion section start
                if "Possible completions:" in line:
                    print_function(f"[DEBUG] Found completions section")
                    in_completions = True
                    continue
                
                # Skip if we haven't reached completions yet
                if not in_completions:
                    continue
                
                # Stop if we hit an error message or prompt
                if any(x in line.lower() for x in ["error:", "syntax error:", "[edit]"]):
                    print_function(f"[DEBUG] Found end of completions: {line}")
                    break
                
                # Parse the completion line
                # Format is typically: "> command           Description"
                line = line.strip()
                if line.startswith('>'):
                    line = line[1:].strip()  # Remove '>' prefix
                
                # Split on multiple spaces to separate command from description
                parts = line.split('  ', 1)
                if parts:
                    word = parts[0].strip()
                    print_function(f"[DEBUG] Found word: '{word}'")
                    
                    # Get the base command (everything up to the last space)
                    base_cmd = partial_cmd.rsplit(' ', 1)[0] if ' ' in partial_cmd else ''
                    current_word = partial_cmd.rsplit(' ', 1)[-1] if ' ' in partial_cmd else partial_cmd
                    
                    print_function(f"[DEBUG] Base command: '{base_cmd}', Current word: '{current_word}'")
                    
                    # Check if the word matches our current word
                    if word.startswith(current_word):
                        if base_cmd:
                            full_completion = f"{base_cmd} {word}"
                        else:
                            full_completion = word
                        print_function(f"[DEBUG] Adding completion: '{full_completion}'")
                        completions.append(full_completion)
            
            # Clear any remaining ? and buffer
            self._shell_channel.send('\x15\n')  # Ctrl+U + newline to clear line
            self._read_until_prompt()
            self._shell_channel.send('\n')  # Extra newline to ensure clean state
            self._read_until_prompt()
            
            print_function(f"[DEBUG] Final completions: {completions}")
            return completions
            
        except Exception as e:
            print_function(f"[DEBUG] ? completion error: {str(e)}\n{traceback.format_exc()}")
            # Ensure we clean up even on error
            self._shell_channel.send('\x15\n')  # Ctrl+U + newline
            self._read_until_prompt()
            self._shell_channel.send('\n')  # Extra newline
            self._read_until_prompt()
            return []

    def _get_completions(self, partial_cmd, print_function=print):
        """Get completion suggestions for a partial command"""
        try:
            # First ensure we're at a clean prompt
            output = self._ensure_clean_prompt()
            print_function(f"[DEBUG] Current prompt: {output.splitlines()[-1] if output else 'No output'}")
            
            # Check if we're in configuration mode
            is_config_mode = '#' in (output.splitlines()[-1] if output else '')
            print_function(f"[DEBUG] In configuration mode: {is_config_mode}")
            
            # In configuration mode, we need to handle the command differently
            if is_config_mode:
                # Try without 'set' first if it's already there
                if partial_cmd.startswith('set '):
                    base_cmd = partial_cmd[4:]
                    print_function(f"[DEBUG] Trying completion without 'set': {base_cmd}")
                    completions = self._get_completions_question_mark(base_cmd, print_function)
                    if completions:
                        # Add 'set' back to the completions
                        return ['set ' + c for c in completions]
                
                # If that didn't work or if 'set' wasn't there, try with the full command
                print_function(f"[DEBUG] Trying completion with full command: {partial_cmd}")
                return self._get_completions_question_mark(partial_cmd, print_function)
            else:
                # In operational mode, just try the command as is
                return self._get_completions_question_mark(partial_cmd, print_function)
            
        except Exception as e:
            print_function(f"[DEBUG] Completion error in _get_completions: {str(e)}\n{traceback.format_exc()}")
            return []

    def get_completions(self, text, print_function=print):
        """Get completion suggestions for the current text"""
        try:
            if not text.strip():
                return []
                
            print_function(f"[DEBUG] Getting completions for: '{text}'")
            # Clean the input text
            text = text.strip()
            
            # Get all possible completions
            completions = self._get_completions(text, print_function)
            
            # Return all completions that extend the current text
            matches = []
            for comp in completions:
                comp = comp.strip()
                print_function(f"[DEBUG] Checking completion: '{comp}' against text: '{text}'")
                # Only add completions that extend the current text
                if comp.startswith(text) and comp != text:
                    print_function(f"[DEBUG] Adding match: '{comp}'")
                    matches.append(comp)
            
            print_function(f"[DEBUG] Final filtered matches: {matches}")
            
            # Sort and remove duplicates while preserving case
            return sorted(list(set(matches)), key=str.lower)
            
        except Exception as e:
            print_function(f"[DEBUG] Completion error: {str(e)}")
            # If anything goes wrong, return empty list
            return [] 