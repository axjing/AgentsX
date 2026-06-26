"""Interactive REPL for AgentsX chat.

Contains the display and command-handling logic for the
interactive chat session.
"""

from __future__ import annotations

import logging

from rich.console import Console
from rich.panel import Panel

from agentsx.cli import commands
from agentsx.core.types import AgentMessage, ToolExecutionEvent
from agentsx.session.store import SessionStore

console = Console()
logger = logging.getLogger(__name__)


def display_tool_event(event: ToolExecutionEvent) -> None:
    """Print a tool-execution event to the console."""
    tc = event.tool_call
    tr = event.result
    prefix = "[green]✓[/green]" if not tr.is_error else "[red]✗[/red]"
    args_str = ", ".join(f"{k}={v!r}" for k, v in tc.arguments.items())
    snippet = tr.content[:300]
    if len(tr.content) > 300:
        snippet += " ..."
    console.print(
        Panel(
            f"[dim]{args_str}[/dim]\n{snippet}",
            title=f"{prefix} {tc.name}",
            border_style="green" if not tr.is_error else "red",
        ),
    )


def handle_command(
    cmd: str,
    messages: list[AgentMessage],
    store: SessionStore | None = None,
    session_id: str = "",
    model_name: str = "unknown",
) -> tuple[str | None, str]:
    """Process a slash command typed by the user.

    Args:
        cmd: The raw command line.
        messages: Current conversation messages (modified in-place for /clear).
        store: SessionStore instance (required for session commands).
        session_id: Current session ID.
        model_name: Current model name (passed to /new for correct session metadata).

    Returns:
        (new_session_id, new_model_name) or (None, current_model).
    """
    """Process a slash command typed by the user.

    Args:
        cmd: The raw command line.
        messages: Current conversation messages (modified in-place for /clear).
        store: SessionStore instance (required for session commands).
        session_id: Current session ID.

    Returns:
        New session ID if the session was switched, or None.
    """
    parts = cmd.split()
    command = parts[0].lower()

    if command in ("/exit", "/quit"):
        raise SystemExit(0)

    if command == "/help":
        console.print(commands.cmd_help())
        return None, model_name

    if command == "/clear":
        messages.clear()
        console.print("[dim]History cleared.[/dim]")
        return None, model_name

    # ── Session commands ─────────────────────────────────────────────
    if store is None:
        console.print("[yellow]Session store not available.[/yellow]")
        return None, model_name

    if command == "/sessions":
        msg, _ = commands.cmd_sessions(store, session_id)
        console.print(msg)
        return None, model_name

    if command == "/session" and len(parts) >= 3 and parts[1] == "show":
        msg, _ = commands.cmd_session_show(store, session_id, parts[2])
        console.print(msg)
        return None, model_name

    if command == "/session" and len(parts) >= 3 and parts[1] == "switch":
        msg, new_id = commands.cmd_session_switch(store, session_id, parts[2])
        console.print(msg)
        return new_id, model_name

    if command == "/new":
        title = " ".join(parts[1:]) if len(parts) > 1 else ""
        msg, new_id = commands.cmd_new(
            store,
            session_id,
            title,
            model_name=model_name,
        )
        console.print(msg)
        return new_id, model_name

    if command == "/delete" and len(parts) >= 2:
        msg, _ = commands.cmd_delete(store, session_id, parts[1])
        console.print(msg)
        return None, model_name

    if command == "/branch" and len(parts) >= 2:
        title = " ".join(parts[2:]) if len(parts) > 2 else ""
        msg, new_id = commands.cmd_branch(store, session_id, parts[1], title)
        console.print(msg)
        return new_id, model_name

    if command == "/title" and len(parts) >= 2:
        title = " ".join(parts[1:])
        msg, _ = commands.cmd_title(store, session_id, title)
        console.print(msg)
        return None, model_name

    console.print(f"[yellow]Unknown command: {command}.  Try /help[/yellow]")
    return None, model_name
