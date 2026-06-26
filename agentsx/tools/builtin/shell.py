"""Shell command execution tool."""

from __future__ import annotations

import subprocess

from agentsx.config import get_settings
from agentsx.tools import tool


@tool(description="Execute a shell command and return its output.")
def tool_bash(
    command: str,
    description: str = "",
    timeout: int = 120,
) -> str:
    """Run a shell command.

    Args:
        command: The command to execute.
        description: Brief description of what the command does.
        timeout: Timeout in seconds (default 120).

    Returns:
        Combined stdout and stderr.
    """
    if timeout == 120:
        settings = get_settings()
        timeout = settings.tool_timeout
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"

    output = result.stdout
    if result.stderr:
        output += "\n--- stderr ---\n" + result.stderr

    output = output.strip()
    if not output:
        return f"Command completed (exit code {result.returncode})"

    return f"Exit code: {result.returncode}\n{output}"
