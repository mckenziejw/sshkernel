"""A ssh kernel for Jupyter"""

from .kernel import SSHKernel
from .ssh_wrapper_paramiko import SSHWrapperParamiko
from .version import __version__

__all__ = ['SSHKernel', 'SSHWrapperParamiko', '__version__']
