import os
import re
import time
import paramiko
from paramiko import SSHException
from .ssh_wrapper import SSHWrapper
import traceback

class SSHWrapperParamiko(SSHWrapper):
    """
    🚀 The Paramiko-powered SSH Wizard!
    
    This class is like a magical portal that connects your Jupyter notebook to remote servers.
    It's built on top of Paramiko (the Swiss Army knife of SSH in Python) and adds some
    special sauce to make it work seamlessly with Jupyter.
    
    Features:
    - 🔐 Handles SSH authentication like a pro
    - 🖥️ Manages shell sessions with style
    - 🎯 Supports command completion for Junos devices
    - 🎭 Handles various prompt types and output formats
    
    Think of it as your personal SSH butler - always ready to serve your remote execution needs!
    """

    def __init__(self, envdelta_init=dict()):
        """
        🎬 Initialize our SSH butler
        
        Args:
            envdelta_init: A dict of environment variables to set on the remote server
                          (because sometimes we need to set the mood just right)
        """
        self.envdelta_init = envdelta_init
        self._client = None         # Our SSH client (waiting to be summoned)
        self._channel = None        # The communication channel (like a tin can phone)
        self.__connected = False    # Are we connected? (initially, we're just dreaming)
        self._host = ""            # The remote host (our destination)
        self._cwd = None           # Current working directory (where are we?)
        self._env = {}             # Environment variables (the weather conditions)
        self._shell_channel = None  # Interactive shell channel (for real-time chat)
        self._shell_buffer = ""     # Buffer for shell output (our memory pad)

    def connect(self, host):
        """
        🔌 Establish connection to the remote server
        
        This is where the magic happens! We:
        1. Load SSH config (like reading a spellbook)
        2. Parse the host (making sure we know where we're going)
        3. Set up the connection (casting the teleportation spell)
        4. Configure the shell (making ourselves at home)
        
        Args:
            host: The remote host to connect to (can be user@host format)
        """
        # Close any existing connections (clean slate policy!)
        if self._client:
            self.close()

        # 🎭 Create and configure our SSH client
        self._client = paramiko.SSHClient()
        self._client.load_system_host_keys()
        self._client.set_missing_host_key_policy(paramiko.WarningPolicy())

        # 📚 Read the SSH config file (our travel guide)
        ssh_config = paramiko.SSHConfig()
        user_config_file = os.path.expanduser("~/.ssh/config")
        if os.path.exists(user_config_file):
            with open(user_config_file) as f:
                ssh_config.parse(f)

        # 🔍 Check if username is in the host string (user@host)
        username_from_host = None
        m = re.search("([^@]+)@(.*)", host)
        if m:
            username_from_host = m.group(1)
            host = m.group(2)

        # 🎯 Get the host's configuration
        cfg = ssh_config.lookup(host)
        
        # 🏗️ Build our connection parameters
        hostname = cfg.get('hostname', host)
        username = username_from_host or cfg.get('user')
        port = int(cfg.get('port', 22))
        key_filename = cfg.get('identityfile', None)
        if isinstance(key_filename, list):
            key_filename = key_filename[0]

        # 🚀 Launch the connection!
        self._client.connect(
            hostname=hostname,
            username=username,
            port=port,
            key_filename=key_filename,
        )

        # 🎉 Set up our cozy environment
        self.__connected = True
        self._host = host
        
        # Initialize environment (making ourselves comfortable)
        self._env.update(self.envdelta_init)
        self._env['PAGER'] = 'cat'  # No paging, we want it all at once!

        # 🎭 Set up our interactive shell
        self._shell_channel = self._client.invoke_shell()
        # Wait for the welcome party
        time.sleep(2)
        self._read_until_prompt()

        # 🎨 Configure Junos CLI settings (making it work just right)
        self._shell_channel.send('set cli complete-on-space off\n')
        self._read_until_prompt()
        self._shell_channel.send('set cli screen-length 0\n')
        self._read_until_prompt()
        
        # Send a newline for good measure (like clearing your throat)
        self._shell_channel.send('\n')
        self._read_until_prompt()

    def _read_until_prompt(self, timeout=30):
        """
        📖 Read shell output until we see a prompt
        
        This is like being a patient listener - we keep reading until the remote
        server says "I'm ready for your next command" (by showing a prompt).
        
        We handle various types of prompts:
        - 👉 Regular prompt (user@host>)
        - 🔧 Config mode (user@host#)
        - 📝 Config with hierarchy ([edit interfaces]user@host#)
        - 🎭 Special states ({master:0}user@host%)
        
        Args:
            timeout: How long to wait (in seconds) before giving up
            
        Returns:
            str: Everything we read until we found a prompt
            
        Raises:
            TimeoutError: If we don't see a prompt within timeout seconds
        """
        buffer = ""
        start_time = time.time()
        
        while True:
            if self._shell_channel.recv_ready():
                chunk = self._shell_channel.recv(4096).decode('utf-8', errors='replace')
                buffer += chunk
                
                # 📜 Handle "More" prompts (because some outputs are chatty)
                if buffer.endswith('---(more)---'):
                    self._shell_channel.send(' ')  # "Please continue..."
                    buffer = buffer[:-12]  # Remove the prompt
                    continue
                elif buffer.endswith('---(more 100%)---'):
                    self._shell_channel.send(' ')  # "Almost there..."
                    buffer = buffer[:-17]  # Remove the prompt
                    continue
                
                # 🔍 Look for various Junos prompts
                if re.search(r'(?:\{master:\d+\})?(?:\[edit[^\]]*\])?[a-zA-Z0-9\-_]+@[a-zA-Z0-9\-_]+[%>#](?:\s+\(pending changes\))?\s*$', buffer):
                    return buffer
                
            # ⏰ Check if we've waited too long
            if time.time() - start_time > timeout:
                raise TimeoutError(f"Timeout waiting for prompt. Buffer received: {buffer}")
                
            time.sleep(0.1)  # Take a short breather

    def _ensure_clean_prompt(self):
        """
        🧹 Make sure we're starting fresh
        
        Sometimes you need to clear the slate before starting something new.
        We send Ctrl+U (clear line) and a newline to make sure we're at a
        clean prompt.
        
        Returns:
            str: The prompt we got back
        """
        self._shell_channel.send('\x15\n')  # Ctrl+U + newline
        return self._read_until_prompt()

    def test_completion(self, cmd, print_function):
        """
        🧪 Test the completion functionality
        
        This is our completion laboratory where we can experiment with
        completion behavior. It's like having a sandbox to play in!
        
        Args:
            cmd: The command to test completion with
            print_function: Function to use for printing debug info
            
        Returns:
            bool: True if test succeeded, False if something went wrong
        """
        try:
            print_function("[DEBUG] Starting completion test")
            
            # Start with a clean slate
            output = self._ensure_clean_prompt()
            print_function(f"[DEBUG] Current prompt:\n{output}")
            
            # Try the completion
            print_function(f"[DEBUG] Sending command: {cmd}?")
            self._shell_channel.send(cmd + '?\n')
            
            # See what we got back
            output = self._read_until_prompt()
            print_function(f"[DEBUG] Response from device:\n{output}")
            
            # Clean up after ourselves
            self._shell_channel.send('\x15\n')  # Ctrl+U + newline
            self._read_until_prompt()
            
            return True
            
        except Exception as e:
            print_function(f"[DEBUG] Test error: {str(e)}\n{traceback.format_exc()}")
            return False

    def exec_command(self, cmd, print_function):
        """
        🎮 Execute a command on the remote server
        
        This is where we actually run commands! Think of it as pressing
        the "Do it!" button for your remote commands.
        
        Args:
            cmd: The command to execute
            print_function: Function to use for output
            
        Returns:
            int: 0 if all went well, 1 if there were problems
        """
        if not self.isconnected():
            raise Exception("Not connected")

        # 🧪 Special handling for test commands
        if cmd.startswith("__test_completion"):
            test_cmd = cmd.split(" ", 1)[1] if " " in cmd else ""
            return 0 if self.test_completion(test_cmd, print_function) else 1

        # Clean up the command
        cmd = cmd.strip()
        print_function(f"[ssh] Sending command: {cmd}\n")
        
        # Send it off!
        self._shell_channel.send(cmd + '\n')
        
        try:
            # Get the response
            output = self._read_until_prompt()
            
            # Clean up the output (remove echoed command and prompt)
            lines = output.split('\n')
            if lines and lines[0].strip() == cmd.strip():
                lines = lines[1:]
            if lines and re.search(r'(?:\{master:\d+\})?(?:\[edit[^\]]*\])?[a-zA-Z0-9\-_]+@[a-zA-Z0-9\-_]+[%>#]\s*$', lines[-1]):
                lines = lines[:-1]
            
            # Look for error messages
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
            
            # Make sure we're ready for the next command
            self._ensure_clean_prompt()
            
            return 1 if has_error else 0
            
        except TimeoutError as e:
            print_function(f"[ssh] Error: {str(e)}\n")
            self._ensure_clean_prompt()
            return 1

    def close(self):
        """
        👋 Close the SSH connection
        
        All good things must come to an end. This method cleans up our
        SSH connection and says goodbye to the remote server.
        """
        self.__connected = False
        if self._shell_channel:
            self._shell_channel.close()
        if self._client:
            self._client.close()
        self._shell_channel = None
        self._client = None

    def interrupt(self):
        """
        🛑 Interrupt the current command
        
        Sometimes you need to tell a command "That's enough!" This method
        sends a Ctrl+C to the remote server to stop the current command.
        """
        if self._shell_channel:
            self._shell_channel.send('\x03')  # Ctrl+C
            time.sleep(0.1)  # Give it a moment
            self._read_until_prompt()  # Clean up

    def isconnected(self):
        """
        🔍 Check if we're connected
        
        Returns:
            bool: True if we're connected, False if we're not
        """
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