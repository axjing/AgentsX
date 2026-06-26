"""Shell command execution tool."""

from __future__ import annotations

import asyncio
import subprocess

from agentsx.config import get_settings
from agentsx.tools import tool


async def _run_command(
    command: str,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    """Run a shell command without blocking the event loop.

    Uses `asyncio.create_subprocess_shell` to keep the event loop
    responsive while the subprocess runs.
    """
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return subprocess.CompletedProcess(
            args=command,
            returncode=-1,
            stdout="",
            stderr=f"command timed out after {timeout}s",
        )

    return subprocess.CompletedProcess(
        args=command,
        returncode=proc.returncode or 0,
        stdout=stdout.decode(errors="replace"),
        stderr=stderr.decode(errors="replace"),
    )


@tool(description="Execute a shell command and return its output.")
async def tool_bash(
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

    result = await _run_command(command, timeout)

    output = result.stdout
    if result.stderr:
        output += "\n--- stderr ---\n" + result.stderr

    output = output.strip()
    if not output:
        return f"Command completed (exit code {result.returncode})"

    return f"Exit code: {result.returncode}\n{output}"
