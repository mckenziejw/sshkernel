# SSH Kernel (Juniper Edition)

This is a custom fork of the [original SSH Kernel project](https://github.com/NII-cloud-operation/sshkernel), modified specifically to interface with Juniper network devices. The kernel provides enhanced support for Juniper CLI commands, command completion, and configuration modes.

SSH Kernel is a Jupyter kernel specialized in executing commands remotely with [paramiko](http://www.paramiko.org/) SSH client.

![](doc/screenshot.png)

## Major requirements

* Python3.5+
* IPython 7.0+

## Recommended system requirements

Host OS (running notebook server):

* Ubuntu 18.04+
* Windows 10 WSL (Ubuntu 18.04+)

Target Devices:

* Juniper network devices with SSH access
* Standard Linux/Unix systems (Ubuntu 16.04+, CentOS 6+)

## Installation

Since this is a custom fork, you'll need to install it from source:

1. Clone the repository:
```bash
git clone <repository_url>
cd sshkernel
```

2. Install in development mode with dependencies:
```bash
pip install -e .
```

3. Install the kernel specification:
```bash
python -m sshkernel install [--user|--sys-prefix]
# Use --user for user-specific installation (recommended)
# Use --sys-prefix for environment/virtualenv-specific installation
```

Verify that sshkernel is installed correctly by listing available Jupyter kernel specs:

```bash
$ jupyter kernelspec list
Available kernels:
  python3        /tmp/env/share/jupyter/kernels/python3
  ssh            /tmp/env/share/jupyter/kernels/ssh  # <--

  (Path differs depends on environment)
```

To uninstall:

```bash
jupyter kernelspec remove ssh
pip uninstall sshkernel
```

### Notes about python environment

The latest version of this library is mainly developed with Python 3.7.3 installed with `pyenv`.

## Getting Started

Basic examples of using SSH Kernel with Juniper devices:

* [Getting Started](https://github.com/NII-cloud-operation/sshkernel/blob/master/examples/getting-started.ipynb)

## Configuration

SSH Kernel obtains configuration data from `~/.ssh/config` file to connect to devices.

Possible keywords are as follows:

* HostName
* User
* Port
* IdentityFile
* ForwardAgent

### Notes about private keys

* As private key files in `~/.ssh/` are discoverable, you do not necessarily specify `IdentityFile`
* If you use a ed25519 key, please generate with or convert into old PEM format
    * e.g. `ssh-keygen -m PEM -t ed25519 ...`
    * This is because `paramiko` library doesn't support latest format "RFC4716"

### Configuration examples

Example for Juniper device:

```
[~/.ssh/config]
Host juniper-switch
  HostName switch.example.com
  User admin
  Port 22
  IdentityFile ~/.ssh/id_rsa_juniper

Host *
  User admin
```

Minimal example:

```
[~/.ssh/config]
Host router
  HostName 192.0.2.1
```

## Juniper-Specific Features

This fork includes several enhancements for working with Juniper devices:

* Support for Juniper CLI command completion
* Handling of configuration modes (`configure`, `edit`, etc.)
* Support for both operational and configuration commands
* Proper handling of Juniper-style prompts and output formatting

## Limitations

* As Jupyter Notebook has limitation to handle `stdin`,
  you may need to change some device configuration and commands to avoid *interactive input*.
  * e.g. use publickey-authentication instead of password
* Some shell variables are different from normal interactive shell
  * e.g. `$?`, `$$`

## LICENSE

This software is released under the terms of the Modified BSD License.

[Logo](https://commons.wikimedia.org/wiki/File:High-contrast-utilities-terminal.png) from Wikimedia Commons is licensed under [CC BY 3.0](https://creativecommons.org/licenses/by/3.0).
