"""Built-in tool implementations.

Tools are organized by risk level:
    - read/: Filesystem read-only tools
    - write/: Filesystem mutation tools
    - exec/: Shell command execution
    - web/: Network fetch/search tools
    - orchestration/: Sub-agent spawning

All tools are exposed via the ``ALL_TOOLS`` constant for easy registration::

    from agentsx.tools.builtin import ALL_TOOLS
    registry.register_all(*ALL_TOOLS)
"""

from __future__ import annotations

from agentsx.tools.builtin.exec.shell import tool_bash
from agentsx.tools.builtin.orchestration.subagent import spawn_agent
from agentsx.tools.builtin.read.filesystem import (
    tool_file_glob,
    tool_file_grep,
    tool_file_read,
)
from agentsx.tools.builtin.web.web import tool_web_fetch, tool_web_search
from agentsx.tools.builtin.write.filesystem import (
    tool_file_edit,
    tool_file_write,
)

ALL_TOOLS = [
    tool_file_read,
    tool_file_write,
    tool_file_edit,
    tool_file_glob,
    tool_file_grep,
    tool_bash,
    tool_web_fetch,
    tool_web_search,
    spawn_agent,
]

__all__ = [
    "ALL_TOOLS",
    "tool_file_read",
    "tool_file_write",
    "tool_file_edit",
    "tool_file_glob",
    "tool_file_grep",
    "tool_bash",
    "spawn_agent",
    "tool_web_fetch",
    "tool_web_search",
]
