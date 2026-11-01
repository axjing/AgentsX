"""Slash commands for the interactive chat REPL.

All session-management commands are defined here and dispatched from
``main.py``'s ``_handle_command()``.  Each command receives the current
``SessionStore`` and session ID, and returns a (message, new_session_id)
tuple so the caller can update its state.
"""

import shutil
import subprocess
from pathlib import Path

from agentsx.context.compaction import compact_messages, should_compact
from agentsx.context.plan import get_active_plan
from agentsx.protocol.errors import SessionError
from agentsx.protocol.messages import AgentMessage, MessageRole
from agentsx.provider import create_provider
from agentsx.session.protocol import SessionBackend
from agentsx.workspace.git import GitWatcher


def cmd_compact(
    store: SessionBackend,
    session_id: str,
    messages: list[AgentMessage],
    force: bool = False,
) -> tuple[str, int]:
    """Trigger manual context compaction.

    Args:
        store: SessionBackend instance.
        session_id: Current session ID.
        messages: Current conversation messages (replaced on success).
        force: If True, skip the ``should_compact()`` threshold check.

    Returns:
        (status_message, new_message_count).
    """
    if not force and not should_compact(messages):
        return (
            f"No compaction needed ({len(messages)} messages). "
            "Use /compact force to override.",
            len(messages),
        )

    old_count = len(messages)
    compacted = compact_messages(messages)
    new_count = len(compacted)

    if new_count >= old_count:
        return "No messages could be compacted.", old_count

    # Record compaction entry in the session store
    replaced_ids = [m.id for m in messages[: old_count - new_count + 1]]
    summary = compacted[1].content if len(compacted) > 1 else "Context compacted"
    try:
        store.append_compaction_entry(
            session_id,
            replaces_ids=replaced_ids,
            summary=summary,
        )
    except SessionError:
        pass  # Session may not be persisted yet — skip silently

    # Replace in-memory messages
    messages.clear()
    messages.extend(compacted)

    return (
        f"Compacted: {old_count} → {new_count} messages "
        f"(saved {old_count - new_count})",
        new_count,
    )


def cmd_sessions(
    store: SessionBackend,
    current_id: str,
) -> tuple[str, str]:
    """List all sessions, marking the active one.

    Returns:
        (formatted_table, current_id_unchanged).
    """
    sessions = store.list_sessions()
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
    store: SessionBackend,
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
    store: SessionBackend,
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
    store: SessionBackend,
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
    store: SessionBackend,
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
    store: SessionBackend,
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
    store: SessionBackend,
    current_id: str,
    title: str,
) -> tuple[str, str]:
    """Rename the current session."""
    try:
        store.update_title(current_id, title)
    except SessionError as exc:
        return f"Error: {exc}", current_id
    return f"Session renamed to '{title}'", current_id


def cmd_verify(project_dir: Path | None = None) -> str:
    """Run project test verification suite.

    Detects common test suites (pytest, npm test, cargo test, go test)
    in the project directory and executes them.

    Args:
        project_dir: Root directory of the project. Defaults to current directory.

    Returns:
        Verification summary string with exit status and test output excerpt.
    """
    root = project_dir or Path.cwd()

    if (root / "pyproject.toml").is_file() or (root / "pytest.ini").is_file():
        runner_name = "pytest"
        cmd = "uv run pytest -q" if shutil.which("uv") else "pytest -q"
    elif (root / "package.json").is_file():
        runner_name = "npm test"
        cmd = "npm test"
    elif (root / "Cargo.toml").is_file():
        runner_name = "cargo test"
        cmd = "cargo test"
    elif (root / "go.mod").is_file():
        runner_name = "go test"
        cmd = "go test ./..."
    else:
        return (
            "No known test suite detected (checked for pyproject.toml, "
            "package.json, Cargo.toml, go.mod)."
        )

    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = (proc.stdout + "\n" + proc.stderr).strip()
        if len(output) > 2000:
            output = output[:500] + "\n...[truncated]...\n" + output[-1500:]

        status = (
            "PASSED" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
        )
        return f"[{runner_name} verification: {status}]\n{output}"
    except subprocess.TimeoutExpired:
        return f"[{runner_name} verification: TIMEOUT after 60s]"
    except (subprocess.SubprocessError, OSError) as exc:
        return f"[{runner_name} verification error: {exc}]"


def cmd_revert(
    store: SessionBackend,
    current_id: str,
    messages: list[AgentMessage],
    reason: str = "",
) -> tuple[str, str | None]:
    """Revert the latest turn and branch to a clean context.

    Finds the start of the latest user turn, trims in-memory messages,
    and forks a new branch in the session store to isolate failed history.

    Args:
        store: SessionBackend instance.
        current_id: Current session ID.
        messages: In-memory conversation messages (modified in-place).
        reason: Optional reason for the revert.

    Returns:
        (status_message, new_session_id or None).
    """
    if not messages:
        return "No messages to revert.", None

    last_user_idx: int | None = None
    for idx in range(len(messages) - 1, -1, -1):
        if messages[idx].role == MessageRole.USER:
            last_user_idx = idx
            break

    if last_user_idx is None:
        return "No user turn found to revert.", None

    target_idx = last_user_idx

    try:
        branch = store.branch(
            current_id,
            title=f"Revert: {reason}" if reason else "Reverted Branch",
            from_message_index=target_idx,
            reason="revert",
        )
        new_id = branch.id
    except SessionError as exc:
        return f"Error branching session: {exc}", None

    del messages[target_idx:]

    desc = f" (reason: {reason})" if reason else ""
    return (
        f"Reverted to turn before message #{target_idx}{desc}. "
        f"Branched to {new_id[:12]}.",
        new_id,
    )


def cmd_memory(action: str = "show") -> str:
    """View or manage persistent learned memory.

    Args:
        action: Either ``"show"`` (default) or ``"clear"``.

    Returns:
        Formatted memory rules or confirmation message.
    """
    proj_mem = Path.cwd() / ".agentsx" / "memory.md"
    glob_mem = Path.home() / ".agentsx" / "memory.md"

    if action in ("clear", "reset"):
        cleared: list[str] = []
        if proj_mem.is_file():
            proj_mem.write_text("", encoding="utf-8")
            cleared.append(str(proj_mem))
        if cleared:
            return f"Cleared project memory ({', '.join(cleared)})."
        return "No project memory file to clear."

    snippets: list[str] = []
    if proj_mem.is_file():
        content = proj_mem.read_text(encoding="utf-8").strip()
        if content:
            snippets.append(f"## Project Memory ({proj_mem}):\n{content}")
    if glob_mem.is_file():
        content = glob_mem.read_text(encoding="utf-8").strip()
        if content:
            snippets.append(f"## Global Memory ({glob_mem}):\n{content}")

    if not snippets:
        return (
            "No persistent memories recorded yet.\n"
            "Use tool_remember to crystallize project rules or lessons."
        )
    return "\n\n".join(snippets)


def cmd_plan(action: str = "view") -> str:
    """View or clear the active multi-step task plan.

    Args:
        action: Either ``"view"`` (default) or ``"clear"``.

    Returns:
        Rendered markdown plan or confirmation message.
    """
    plan = get_active_plan()
    if action in ("clear", "reset"):
        plan.clear()
        return "Active task plan cleared."

    if not plan.tasks:
        return "No active task plan. (Use tool_plan to create tasks)"
    return plan.render_markdown()


def cmd_model(current_model: str, new_model: str = "") -> tuple[str, str]:
    """Display or switch the active LLM model.

    Args:
        current_model: The currently active model name.
        new_model: Target model name to switch to (empty = view only).

    Returns:
        (status_message, updated_model_name).
    """
    clean_target = new_model.strip()
    if not clean_target:
        return f"Current model: {current_model}", current_model

    try:
        # Validate that a provider instance can be created
        create_provider(clean_target)
    except (ValueError, KeyError, RuntimeError, OSError) as exc:
        return (
            f"Error creating provider for '{clean_target}': {exc}",
            current_model,
        )

    return f"Model switched to '{clean_target}'", clean_target


def cmd_status(
    session_id: str,
    model_name: str,
    messages: list[AgentMessage],
    workspace_root: Path | None = None,
    token_stats: dict[str, int] | None = None,
) -> str:
    """Return unified status summary of the session, model, context, and git workspace.

    Args:
        session_id: Current active session ID.
        model_name: Current active model name.
        messages: Active conversation messages list.
        workspace_root: Workspace root directory. Defaults to current working directory.
        token_stats: Optional cumulative token statistics dict.

    Returns:
        Formatted multi-line status summary.
    """
    root = workspace_root or Path.cwd()
    msg_count = len(messages)
    approx_tokens = sum(len(m.content) for m in messages) // 4

    watcher = GitWatcher(root)
    git_status = watcher.get_status()

    if git_status.error:
        git_info = f"Git        : {git_status.error}"
    else:
        dirty_flag = "dirty" if git_status.is_dirty else "clean"
        mod_count = len(git_status.modified_files or [])
        git_info = (
            f"Git        : branch '{git_status.branch}' ({dirty_flag}, "
            f"{mod_count} modified, {git_status.untracked_count} untracked)"
        )

    plan = get_active_plan()
    if plan.tasks:
        done = plan.completed_count
        plan_info = f"Plan       : {done}/{plan.total_count} tasks completed"
    else:
        plan_info = "Plan       : no active plan"

    sid_display = (
        session_id[:12] + "..." if len(session_id) > 12 else (session_id or "none")
    )

    lines = [
        "Session Status:",
        f"  Session ID : {sid_display}",
        f"  Model      : {model_name}",
        f"  Context    : {msg_count} messages (~{approx_tokens} tokens)",
    ]

    if token_stats and token_stats.get("total_tokens", 0) > 0:
        total = token_stats["total_tokens"]
        prompt = token_stats.get("prompt_tokens", 0)
        completion = token_stats.get("completion_tokens", 0)
        cached = token_stats.get("cached_tokens", 0)
        hit_rate = (cached / prompt * 100) if prompt > 0 else 0.0
        lines.append(
            f"  Tokens     : {total} total ({prompt} in, {completion} out) "
            f"| Cache Hit: {hit_rate:.1f}% ({cached} tokens)"
        )

    lines.extend(
        [
            f"  Workspace  : {root}",
            f"  {git_info}",
            f"  {plan_info}",
        ]
    )
    return "\n".join(lines)


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
        "  /status                   Show session, model & workspace status\n"
        "  /model [name]             Show or switch active model\n"
        "  /compact [force]          Manually compact context\n"
        "  /memory [show|clear]      View or clear persistent memory\n"
        "  /plan [view|clear]        View or clear active task plan\n"
        "  /verify                   Run test verification suite\n"
        "  /revert [reason]          Rollback failed turn & branch\n"
        "  /clear                    Clear conversation history\n"
        "  /help                     Show this message\n"
        "  /exit, /quit              Exit the chat"
    )
