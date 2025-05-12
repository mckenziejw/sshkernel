import re
import sys
import textwrap
import traceback
from logging import INFO

from metakernel import ExceptionWrapper
from metakernel import MetaKernel

from paramiko.ssh_exception import SSHException

from .exception import SSHKernelNotConnectedException
from .ssh_wrapper_paramiko import SSHWrapperParamiko
from .version import __version__

# 🎯 This regex helps us extract version numbers like "1.2.3" from strings
version_pat = re.compile(r"version (\d+(\.\d+)+)")


class SSHKernel(MetaKernel):
    """
    🚀 The SSH Kernel - Your Gateway to Remote Command Execution! 
    
    Think of this as your friendly neighborhood Spider-Man, but for SSH connections.
    It swings between your Jupyter notebook and remote servers, executing commands
    and bringing back results faster than you can say "with great power comes great
    responsibility!"

    Key Features:
    - 🔑 Handles SSH authentication automagically
    - 🖥️ Executes commands on remote machines
    - 🏃 Supports command completion (like a psychic for your terminal!)
    - 🎮 Manages remote sessions like a boss
    """

    # 📝 Basic kernel info - like our superhero's ID card
    implementation = "sshkernel"
    implementation_version = __version__
    language = "bash"  # We speak bash, but we're not limited by it!
    language_version = __version__
    banner = "SSH Custom kernel version {}".format(__version__)

    # 🎭 Our kernel's secret identity - how Jupyter sees us
    kernel_json = {
        "argv": [sys.executable, "-m", "sshkernel", "-f", "{connection_file}"],
        "display_name": "SSH Custom",
        "language": "bash",
        "codemirror_mode": "shell",
        "env": {"PS1": "$"},  # The classic dollar prompt, keeping it old school
        "name": "ssh_custom",
    }

    # 🎨 How our kernel presents itself to the IDE
    language_info = {
        "name": "ssh_custom",
        "codemirror_mode": "shell",
        "mimetype": "text/x-sh",
        "file_extension": ".sh",
    }

    @property
    def sshwrapper(self):
        """🎁 Get our SSH wrapper - it's like getting the keys to the batmobile"""
        return self._sshwrapper

    @sshwrapper.setter
    def sshwrapper(self, value):
        """🔧 Set our SSH wrapper - parking the batmobile in the batcave"""
        self._sshwrapper = value

    def get_usage(self):
        """
        📚 Returns a user-friendly guide on how to use this kernel
        
        It's like the instruction manual, but actually readable!
        """
        return textwrap.dedent(
            """Usage:

        * Prepare `~/.ssh/config`
        * To login to the remote server, use magic command `%login <host_in_ssh_config>` into a new cell
            * e.g. `%login localhost`
        * After %login, input commands are executed remotely
        * To close session, use `%logout` magic command
        """
        )

    def __init__(self, sshwrapper_class=SSHWrapperParamiko, **kwargs):
        """
        🎬 The origin story - where our kernel gets its superpowers
        
        Args:
            sshwrapper_class: The class that handles SSH connections (default: SSHWrapperParamiko)
            **kwargs: Additional arguments passed to the parent class
        """
        super().__init__(**kwargs)

        self.__sshwrapper_class = sshwrapper_class  # Our SSH sidekick
        self._sshwrapper = None  # No connection yet
        self._parameters = dict()  # Empty utility belt

        # 📝 Set up our log book
        self.log.name = "SSHKernel"
        self.log.setLevel(INFO)

    def set_param(self, key, value):
        """
        🎒 Add something to our utility belt
        
        Args:
            key: The name of the gadget
            value: What the gadget does
        """
        self._parameters[key] = value

    def get_params(self):
        """
        📋 Check what's in our utility belt
        
        Returns:
            dict: All our parameters and their values
        """
        return self._parameters

    def do_login(self, host: str):
        """
        🔓 Open a portal to a remote server
        
        Args:
            host: The server we want to connect to
        """
        self.do_logout()  # Close any existing portals first

        wrapper = self.__sshwrapper_class(self.get_params())
        wrapper.connect(host)
        self.sshwrapper = wrapper

    def do_logout(self):
        """
        🔒 Close our portal to the remote server
        
        Like Spider-Man going home after a long day of web-slinging
        """
        if self.sshwrapper:
            self.Print("[ssh] Closing existing connection.")
            self.sshwrapper.close()
            self.Print("[ssh] Successfully logged out.")

        self.sshwrapper = None

    def do_execute_direct(self, code, silent=False):
        """
        🎯 Execute code on the remote server
        
        This is where the magic happens! We send your code through our SSH portal
        and bring back the results.
        
        Args:
            code: The command to execute
            silent: If True, be ninja-quiet about it
            
        Returns:
            None if successful, ExceptionWrapper if something goes wrong
        """
        try:
            self.assert_connected()
        except SSHKernelNotConnectedException:
            self.Error(traceback.format_exc())
            return ExceptionWrapper("abort", "not connected", [])

        try:
            exitcode = self.sshwrapper.exec_command(code, self.Write)

        except KeyboardInterrupt:
            self.Error("* interrupt...")
            self.sshwrapper.interrupt()
            self.Error(traceback.format_exc())
            return ExceptionWrapper("abort", str(1), [str(KeyboardInterrupt)])

        except SSHException:
            return ExceptionWrapper("ssh_exception", str(1), [])

        if exitcode:
            ename = "abnormal exit code"
            evalue = str(exitcode)
            trace = [""]
            return ExceptionWrapper(ename, evalue, trace)

        return None

    def do_complete(self, code, cursor_pos):
        """
        🔮 The crystal ball of command completion!
        
        This method is like having autocomplete superpowers. It tries to guess
        what command you're trying to type before you finish typing it.
        
        Args:
            code: The partial command you've typed
            cursor_pos: Where your cursor is in the command
            
        Returns:
            dict: Possible completions and cursor position info
        """
        # 📝 Keep a log of what we're doing (for when things go wrong)
        with open('/tmp/kernel_debug.log', 'a') as f:
            f.write(f"\nCompletion request: code='{code}', cursor_pos={cursor_pos}\n")

        # 🎲 Default response - like having a backup plan
        default = {
            "matches": [],
            "cursor_start": 0,
            "cursor_end": cursor_pos,
            "metadata": dict(),
            "status": "ok",
        }

        # 🔍 First, make sure we're connected to a server
        try:
            self.assert_connected()
        except SSHKernelNotConnectedException:
            self.log.error("not connected")
            with open('/tmp/kernel_debug.log', 'a') as f:
                f.write("Not connected\n")
            return default

        # 🎯 Get the part of the command we're working with
        code_current = code[:cursor_pos]
        if not code_current:
            with open('/tmp/kernel_debug.log', 'a') as f:
                f.write("No current code\n")
            return default

        # 🔨 Break the command into pieces we can work with
        tokens = code_current.replace(";", " ").split()
        if not tokens:
            with open('/tmp/kernel_debug.log', 'a') as f:
                f.write("No tokens\n")
            return default

        # 🎭 Get the full context of what we're completing
        command_context = " ".join(tokens)
        token = tokens[-1]
        token_start = code_current.rindex(token)

        with open('/tmp/kernel_debug.log', 'a') as f:
            f.write(f"Command context: '{command_context}'\n")

        self.Print(f"[DEBUG] Attempting completion for command: '{command_context}'")

        # 🎣 Fish for completions from our SSH wrapper
        matches = self.sshwrapper.get_completions(command_context, self.Print)

        with open('/tmp/kernel_debug.log', 'a') as f:
            f.write(f"Got matches: {matches}\n")

        self.Print(f"[DEBUG] Got raw matches: {matches}")

        if matches:
            # 🎯 Filter out the good stuff
            valid_matches = []
            for match in matches:
                if match.startswith(command_context) and match != command_context:
                    # Just get the new part we want to add
                    completion = match[len(command_context):].lstrip()
                    if completion:
                        # Add a space after completion (because we're nice like that)
                        completion = completion + ' '
                        self.Print(f"[DEBUG] Adding completion: '{completion}'")
                        valid_matches.append(completion)

            if valid_matches:
                self.Print(f"[DEBUG] Final valid matches: {valid_matches}")
                with open('/tmp/kernel_debug.log', 'a') as f:
                    f.write(f"Returning valid matches: {valid_matches}\n")
                return {
                    "matches": valid_matches,
                    "cursor_start": cursor_pos,  # Start from cursor position
                    "cursor_end": cursor_pos,    # End at cursor position
                    "metadata": dict(),
                    "status": "ok",
                }

        self.Print("[DEBUG] No valid completions found")
        with open('/tmp/kernel_debug.log', 'a') as f:
            f.write("No valid completions\n")
        return default

    def restart_kernel(self):
        """
        🔄 Turn it off and on again
        
        Sometimes the best solution is a fresh start!
        """
        self.do_logout()
        self._parameters = dict()

    def assert_connected(self):
        """
        🔌 Make sure we're actually connected
        
        Like checking if your Spider-Man web shooters are working before jumping off a building
        
        Raises:
            SSHKernelNotConnectedException: If we're not connected
        """
        if self.sshwrapper is None:
            self.Error("[ssh] Not logged in.")
            raise SSHKernelNotConnectedException

        if not self.sshwrapper.isconnected():
            self.Error("[ssh] Not connected.")
            raise SSHKernelNotConnectedException

    def complete_code(self, code, cursor_pos):
        """
        🎮 The completion game controller
        
        This is our custom implementation of code completion that makes sure
        we're using our special SSH-aware completion instead of the default.
        
        Args:
            code: The code being typed
            cursor_pos: Where the cursor is
            
        Returns:
            dict: Completion suggestions
        """
        with open('/tmp/kernel_debug.log', 'a') as f:
            f.write(f"\nComplete_code called: code='{code}', cursor_pos={cursor_pos}\n")
        
        return self.do_complete(code, cursor_pos)

    def handle_complete_request(self, stream, ident, parent):
        """
        🎭 The completion request handler
        
        This is where we intercept completion requests and make sure they're
        handled by our custom completion logic.
        
        Args:
            stream: The communication stream
            ident: Message identifier
            parent: Parent message
        """
        with open('/tmp/kernel_debug.log', 'a') as f:
            f.write("\nHandle_complete_request called\n")
        
        super().handle_complete_request(stream, ident, parent)
