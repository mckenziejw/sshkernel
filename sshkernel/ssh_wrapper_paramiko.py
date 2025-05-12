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

    def exec_command(self, cmd, print_function):
        """Execute command and stream output"""
        if not self.isconnected():
            raise Exception("Not connected")

        # Create a new channel for this command
        self._channel = self._client.get_transport().open_session()
        
        # Set environment variables directly on the channel
        for key, value in self._env.items():
            try:
                self._channel.set_environment_variable(key, value)
            except SSHException:
                # If setting environment variables fails, continue anyway
                pass
        
        print_function(f"[ssh] host = {self._host}\n")
        self._channel.exec_command(cmd)

        # Read output
        while True:
            # Read from stdout
            while self._channel.recv_ready():
                data = self._channel.recv(4096).decode('utf-8', errors='replace')
                if data:
                    print_function(data)
            
            # Read from stderr
            while self._channel.recv_stderr_ready():
                data = self._channel.recv_stderr(4096).decode('utf-8', errors='replace')
                if data:
                    print_function(data)
            
            # Check if the channel is closed and no more data
            if self._channel.exit_status_ready():
                # Do one final read from both streams
                while self._channel.recv_ready():
                    data = self._channel.recv(4096).decode('utf-8', errors='replace')
                    if data:
                        print_function(data)
                
                while self._channel.recv_stderr_ready():
                    data = self._channel.recv_stderr(4096).decode('utf-8', errors='replace')
                    if data:
                        print_function(data)
                
                break
            
            time.sleep(0.1)

        exit_code = self._channel.recv_exit_status()
        self._channel = None
        return exit_code

    def close(self):
        """Close the SSH connection"""
        self.__connected = False
        if self._channel:
            self._channel.close()
        if self._client:
            self._client.close()
        self._channel = None
        self._client = None

    def interrupt(self):
        """Interrupt the current command"""
        if self._channel:
            self._channel.close()

    def isconnected(self):
        """Check if connected to remote host"""
        return self.__connected 