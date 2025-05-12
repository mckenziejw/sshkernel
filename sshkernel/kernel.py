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

version_pat = re.compile(r"version (\d+(\.\d+)+)")


class SSHKernel(MetaKernel):
    """
    SSH kernel run commands remotely.
    """

    implementation = "sshkernel"
    implementation_version = __version__
    language = "bash"
    language_version = __version__
    banner = "SSH Custom kernel version {}".format(__version__)
    kernel_json = {
        "argv": [sys.executable, "-m", "sshkernel", "-f", "{connection_file}"],
        "display_name": "SSH Custom",
        "language": "bash",
        "codemirror_mode": "shell",
        "env": {"PS1": "$"},
        "name": "ssh_custom",
    }
    language_info = {
        "name": "ssh_custom",
        "codemirror_mode": "shell",
        "mimetype": "text/x-sh",
        "file_extension": ".sh",
    }

    @property
    def sshwrapper(self):
        return self._sshwrapper

    @sshwrapper.setter
    def sshwrapper(self, value):
        self._sshwrapper = value

    def get_usage(self):
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
        super().__init__(**kwargs)

        self.__sshwrapper_class = sshwrapper_class
        self._sshwrapper = None
        self._parameters = dict()

        # Touch inherited attribute
        self.log.name = "SSHKernel"
        self.log.setLevel(INFO)

    def set_param(self, key, value):
        """
        Set sshkernel parameter for hostname and remote envvars.
        """

        self._parameters[key] = value

    def get_params(self):
        """
        Get sshkernel parameters dict.
        """

        return self._parameters

    def do_login(self, host: str):
        """Establish a ssh connection to the host."""
        self.do_logout()

        wrapper = self.__sshwrapper_class(self.get_params())
        wrapper.connect(host)
        self.sshwrapper = wrapper

    def do_logout(self):
        """Close the connection."""
        if self.sshwrapper:
            self.Print("[ssh] Closing existing connection.")
            self.sshwrapper.close()  # TODO: error handling
            self.Print("[ssh] Successfully logged out.")

        self.sshwrapper = None

    # Implement base class method
    def do_execute_direct(self, code, silent=False):
        try:
            self.assert_connected()
        except SSHKernelNotConnectedException:
            self.Error(traceback.format_exc())
            return ExceptionWrapper("abort", "not connected", [])

        try:
            exitcode = self.sshwrapper.exec_command(code, self.Write)

        except KeyboardInterrupt:
            self.Error("* interrupt...")

            # TODO: Handle exception
            self.sshwrapper.interrupt()

            self.Error(traceback.format_exc())

            return ExceptionWrapper("abort", str(1), [str(KeyboardInterrupt)])

        except SSHException:
            #
            # TODO: Implement reconnect sequence
            return ExceptionWrapper("ssh_exception", str(1), [])

        if exitcode:
            ename = "abnormal exit code"
            evalue = str(exitcode)
            trace = [""]

            return ExceptionWrapper(ename, evalue, trace)

        return None

    # Implement ipykernel method
    def do_complete(self, code, cursor_pos):
        """Handle code completion requests."""
        # Basic debug to file to verify we're being called
        with open('/tmp/kernel_debug.log', 'a') as f:
            f.write(f"\nCompletion request: code='{code}', cursor_pos={cursor_pos}\n")

        default = {
            "matches": [],
            "cursor_start": 0,
            "cursor_end": cursor_pos,
            "metadata": dict(),
            "status": "ok",
        }

        try:
            self.assert_connected()
        except SSHKernelNotConnectedException:
            self.log.error("not connected")
            with open('/tmp/kernel_debug.log', 'a') as f:
                f.write("Not connected\n")
            return default

        # Get the current line up to the cursor
        code_current = code[:cursor_pos]
        if not code_current:
            with open('/tmp/kernel_debug.log', 'a') as f:
                f.write("No current code\n")
            return default

        # Get the last token (word) that we're trying to complete
        tokens = code_current.replace(";", " ").split()
        if not tokens:
            with open('/tmp/kernel_debug.log', 'a') as f:
                f.write("No tokens\n")
            return default

        # Get the full command up to the cursor for context
        command_context = " ".join(tokens)
        token = tokens[-1]
        token_start = code_current.rindex(token)

        with open('/tmp/kernel_debug.log', 'a') as f:
            f.write(f"Command context: '{command_context}'\n")

        self.Print(f"[DEBUG] Attempting completion for command: '{command_context}'")

        # Get completions from the SSH wrapper
        matches = self.sshwrapper.get_completions(command_context, self.Print)

        with open('/tmp/kernel_debug.log', 'a') as f:
            f.write(f"Got matches: {matches}\n")

        self.Print(f"[DEBUG] Got raw matches: {matches}")

        if matches:
            # Filter matches to only those that extend the current token
            valid_matches = []
            for match in matches:
                if match.startswith(command_context) and match != command_context:
                    # Extract just the completion part (don't include the token)
                    completion = match[len(command_context):].lstrip()
                    if completion:
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
        # TODO: log message
        # self.Print('[INFO] Restart sshkernel ...')

        self.do_logout()
        self._parameters = dict()

    def assert_connected(self):
        """
        Assert client is connected.
        """

        if self.sshwrapper is None:
            self.Error("[ssh] Not logged in.")
            raise SSHKernelNotConnectedException

        if not self.sshwrapper.isconnected():
            self.Error("[ssh] Not connected.")
            raise SSHKernelNotConnectedException

    def complete_code(self, code, cursor_pos):
        """Override MetaKernel method to ensure our completion is called"""
        with open('/tmp/kernel_debug.log', 'a') as f:
            f.write(f"\nComplete_code called: code='{code}', cursor_pos={cursor_pos}\n")
        
        return self.do_complete(code, cursor_pos)

    def handle_complete_request(self, stream, ident, parent):
        """Override MetaKernel method to ensure completion requests are handled"""
        with open('/tmp/kernel_debug.log', 'a') as f:
            f.write("\nHandle_complete_request called\n")
        
        super().handle_complete_request(stream, ident, parent)
