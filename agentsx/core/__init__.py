"""Backward-compatibility shim.

All types have moved to ``agentsx.protocol``.
Importing from ``agentsx.core`` will continue to work but is deprecated.
"""

from agentsx.protocol import *  # noqa: F401, F403
from agentsx.protocol import __all__  # noqa: F401
