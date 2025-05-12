from abc import ABC, abstractmethod


class SSHWrapper(ABC):
    """
    🎭 The SSH Wrapper Interface - The Master Plan!
    
    Think of this as the blueprint for building SSH wrappers. It's like a recipe
    that says "to make a proper SSH wrapper, you need these ingredients..."
    
    This is an abstract base class (ABC) which means:
    - 🏗️ You can't use it directly (it's like a blueprint, not a building)
    - 📝 Any class that inherits from it MUST implement all its methods
    - 🎯 It ensures all SSH wrappers have the same basic capabilities
    
    It's like being the director of a play - you're setting the stage and
    telling the actors what scenes they need to perform, but not exactly
    how to perform them!
    """
    
    @abstractmethod
    def __init__(self, envdelta):
        """
        🎬 The Setup Scene
        
        This is where we prepare our SSH wrapper with its initial configuration.
        Like setting up the stage before the show begins!
        
        Args:
            envdelta (dict): Environment variables to inject into the remote system
                            (Like setting up the props before the performance)
        """

    @abstractmethod
    def exec_command(self, cmd, print_function):
        """
        🎮 The Command Execution Scene
        
        This is where the actual command running happens! It's like giving
        instructions to an actor and watching them perform.
        
        Args:
            cmd (string): The command to execute (the script for our actor)
            print_function (lambda): How to display the output (like the stage lights)

        Returns:
            int: Exit code (was the performance successful?)
        """

    @abstractmethod
    def connect(self, host):
        """
        🔌 The Connection Scene
        
        Establish connection to a remote host. It's like opening the curtains
        and starting the show!
        
        Args:
            host: The remote host to connect to (our stage location)
        
        Raises:
            SSHConnectionError: If the connection fails (stage fright!)
        """

    @abstractmethod
    def close(self):
        """
        👋 The Closing Scene
        
        Close the connection to the host. Like taking a bow and closing
        the curtains after a successful performance!
        """

    @abstractmethod
    def interrupt(self):
        """
        🛑 The Interruption Scene
        
        Sometimes you need to stop the show mid-performance! This sends
        a SIGINT (like yelling "CUT!" in the middle of a scene).
        """

    @abstractmethod
    def isconnected(self):
        """
        🔍 The Connection Check Scene
        
        Are we still connected? Like checking if the audience is still watching!
        
        Returns:
            bool: True if connected (the show is on!), False otherwise
        """
