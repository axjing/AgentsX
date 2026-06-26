"""Built-in tool implementations.

All tools are exposed via the ``ALL_TOOLS`` constant for easy registration::

    from agentsx.tools.builtin import ALL_TOOLS
    registry.register_all(*ALL_TOOLS)
"""

from __future__ import annotations

from agentsx.tools.builtin.filesystem import (
    tool_file_edit,
    tool_file_glob,
    tool_file_grep,
    tool_file_read,
    tool_file_write,
)
from agentsx.tools.builtin.shell import tool_bash
from agentsx.tools.builtin.subagent import spawn_agent
from agentsx.tools.builtin.web import tool_web_fetch, tool_web_search

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
