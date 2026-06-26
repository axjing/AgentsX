"""Slash commands for the interactive chat REPL.

All session-management commands are defined here and dispatched from
``main.py``'s ``_handle_command()``.  Each command receives the current
``SessionStore`` and session ID, and returns a (message, new_session_id)
tuple so the caller can update its state.
"""

from __future__ import annotations

from agentsx.core.errors import SessionError
from agentsx.session.store import SessionStore


def cmd_sessions(
    store: SessionStore,
    current_id: str,
) -> tuple[str, str]:
    """List all sessions, marking the active one.

    Returns:
        (formatted_table, current_id_unchanged).
    """
    sessions = store.list()
    if not sessions:
        return "No sessions yet.  Start a new chat to create one.", current_id

    lines: list[str] = []
    for s in sessions:
        marker = " <-- active" if s.id == current_id else ""
        msg_count = len(store.get_messages(s.id))
        lines.append(
            f"  {s.id[:12]}  {s.title:30s}  {msg_count:3d} msgs  {marker}",
        )
    return "\n".join(lines), current_id


def cmd_session_show(
    store: SessionStore,
    _current_id: str,
    session_id: str,
) -> tuple[str, str]:
    """Show details for a specific session."""
    try:
        session = store.get(session_id)
    except SessionError as exc:
        return f"Error: {exc}", _current_id

    msgs = store.get_messages(session_id)
    preview_lines: list[str] = []
    for m in msgs[-5:]:
        role_tag = m.role.value.upper()
        content = m.content[:80].replace("\n", " ")
        preview_lines.append(f"  [{role_tag}] {content}")

    lines = [
        f"Session: {session.id}",
        f"Title:   {session.title}",
        f"Model:   {session.model_name}",
        f"Created: {session.created_at.isoformat()}",
        f"Updated: {session.updated_at.isoformat()}",
        f"Messages: {len(msgs)}",
        "",
        "Recent messages:",
        *preview_lines,
    ]
    return "\n".join(lines), _current_id


def cmd_session_switch(
    store: SessionStore,
    _current_id: str,
    session_id: str,
) -> tuple[str, str]:
    """Switch to a different session (return its id)."""
    try:
        store.get(session_id)  # validate existence
    except SessionError as exc:
        return f"Error: {exc}", _current_id
    return f"Switched to session {session_id[:12]}", session_id


def cmd_new(
    store: SessionStore,
    _current_id: str,
    title: str = "",
    model_name: str = "unknown",
) -> tuple[str, str]:
    """Create a new session and switch to it."""
    session = store.create(
        model_name=model_name,
        title=title or "",
    )
    return f"Created new session {session.id[:12]}", session.id


def cmd_delete(
    store: SessionStore,
    current_id: str,
    session_id: str,
) -> tuple[str, str]:
    """Delete a session.  Cannot delete the active session."""
    if session_id == current_id:
        return "Error: cannot delete the active session.  Switch first.", current_id
    try:
        store.delete(session_id)
    except SessionError as exc:
        return f"Error: {exc}", current_id
    return f"Deleted session {session_id[:12]}", current_id


def cmd_branch(
    store: SessionStore,
    _current_id: str,
    source_id: str,
    title: str = "",
) -> tuple[str, str]:
    """Branch from an existing session and switch to the new one."""
    try:
        branch = store.branch(source_id, title=title)
    except SessionError as exc:
        return f"Error: {exc}", _current_id
    return (
        f"Created branch {branch.id[:12]} from {source_id[:12]}",
        branch.id,
    )


def cmd_title(
    store: SessionStore,
    current_id: str,
    title: str,
) -> tuple[str, str]:
    """Rename the current session."""
    try:
        session = store.get(current_id)
        session.title = title
        store._write_meta(session)
    except SessionError as exc:
        return f"Error: {exc}", current_id
    return f"Session renamed to '{title}'", current_id


def cmd_help() -> str:
    """Return available commands help text."""
    return (
        "Commands:\n"
        "  /sessions                 List all sessions\n"
        "  /session show <id>        Show session details\n"
        "  /session switch <id>      Switch to a session\n"
        "  /new [title]              Create a new session\n"
        "  /delete <id>              Delete a session\n"
        "  /branch <id> [title]      Branch from a session\n"
        "  /title <name>             Rename current session\n"
        "  /clear                    Clear conversation history\n"
        "  /help                     Show this message\n"
        "  /exit, /quit              Exit the chat"
    )
