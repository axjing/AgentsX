"""Tests for CLI commands (``agentsx/cli/commands.py``)."""

from pathlib import Path
from unittest.mock import patch

import pytest

from agentsx.cli.commands import (
    cmd_branch,
    cmd_delete,
    cmd_help,
    cmd_memory,
    cmd_model,
    cmd_new,
    cmd_plan,
    cmd_session_show,
    cmd_session_switch,
    cmd_sessions,
    cmd_status,
    cmd_title,
)
from agentsx.context.plan import get_active_plan
from agentsx.protocol.messages import AgentMessage, MessageRole
from agentsx.session.store import SessionStore


@pytest.fixture
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(base_dir=tmp_path / "sessions")


class TestCmdSessions:
    """``/sessions`` — list all sessions."""

    def test_empty(self, store: SessionStore) -> None:
        msg, new_id = cmd_sessions(store, "current")
        assert "No sessions yet" in msg
        assert new_id == "current"

    def test_with_sessions(self, store: SessionStore) -> None:
        s1 = store.create("gpt-4o", "Chat A")
        store.create("claude", "Chat B")
        msg, _ = cmd_sessions(store, s1.id)
        assert "Chat A" in msg
        assert "Chat B" in msg
        assert "active" in msg or "<--" in msg


class TestCmdSessionShow:
    """``/session show <id>`` — show session details."""

    def test_show(self, store: SessionStore) -> None:
        s = store.create("gpt-4o", "Test Chat")
        msg, _ = cmd_session_show(store, s.id, s.id)
        assert s.id in msg
        assert "gpt-4o" in msg
        assert "Test Chat" in msg

    def test_not_found(self, store: SessionStore) -> None:
        msg, _ = cmd_session_show(store, "current", "nonexistent")
        assert "Error" in msg


class TestCmdSessionSwitch:
    """``/session switch <id>`` — switch session."""

    def test_switch(self, store: SessionStore) -> None:
        s = store.create("gpt-4o")
        msg, new_id = cmd_session_switch(store, "old", s.id)
        assert new_id == s.id
        assert "Switched" in msg

    def test_not_found(self, store: SessionStore) -> None:
        msg, new_id = cmd_session_switch(store, "old", "bad")
        assert "Error" in msg
        assert new_id == "old"


class TestCmdNew:
    """``/new [title]`` — create new session."""

    def test_new_without_title(self, store: SessionStore) -> None:
        msg, new_id = cmd_new(store, "old")
        assert new_id != "old"
        assert "Created" in msg

    def test_new_with_title(self, store: SessionStore) -> None:
        msg, new_id = cmd_new(store, "old", "My Session")
        assert "My Session" in msg or "Created" in msg
        loaded = store.get(new_id)
        assert loaded.title == "My Session"


class TestCmdDelete:
    """``/delete <id>`` — delete a session."""

    def test_delete(self, store: SessionStore) -> None:
        s = store.create("gpt-4o")
        msg, new_id = cmd_delete(store, "other", s.id)
        assert "Deleted" in msg
        assert new_id == "other"

    def test_delete_active(self, store: SessionStore) -> None:
        s = store.create("gpt-4o")
        msg, new_id = cmd_delete(store, s.id, s.id)
        assert "cannot delete" in msg
        assert new_id == s.id


class TestCmdBranch:
    """``/branch <id> [title]`` — branch from a session."""

    def test_branch(self, store: SessionStore) -> None:
        s = store.create("gpt-4o", "Original")
        msg, new_id = cmd_branch(store, "old", s.id, "Fork")
        assert new_id != s.id
        assert "Created branch" in msg
        loaded = store.get(new_id)
        assert loaded.title == "Fork"

    def test_branch_not_found(self, store: SessionStore) -> None:
        msg, new_id = cmd_branch(store, "old", "nonexistent")
        assert "Error" in msg
        assert new_id == "old"


class TestCmdTitle:
    """``/title <name>`` — rename current session."""

    def test_rename(self, store: SessionStore) -> None:
        s = store.create("gpt-4o", "Old Name")
        msg, new_id = cmd_title(store, s.id, "New Name")
        assert "renamed" in msg
        assert new_id == s.id
        loaded = store.get(s.id)
        assert loaded.title == "New Name"


class TestCmdMemory:
    """``/memory [show|clear]`` — view or clear memory."""

    def test_memory_empty(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path / "proj")  # type: ignore[attr-defined]
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")  # type: ignore[attr-defined]
        msg = cmd_memory("show")
        assert "No persistent memories recorded yet" in msg

    def test_memory_show_and_clear(self, tmp_path: Path, monkeypatch: object) -> None:
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir(parents=True)
        home_dir = tmp_path / "home"
        home_dir.mkdir(parents=True)
        monkeypatch.setattr(Path, "cwd", lambda: proj_dir)  # type: ignore[attr-defined]
        monkeypatch.setattr(Path, "home", lambda: home_dir)  # type: ignore[attr-defined]

        mem_file = proj_dir / ".agentsx" / "memory.md"
        mem_file.parent.mkdir(parents=True)
        mem_file.write_text("- Rule 1: Always verify.\n", encoding="utf-8")

        show_msg = cmd_memory("show")
        assert "Project Memory" in show_msg
        assert "- Rule 1: Always verify." in show_msg

        clear_msg = cmd_memory("clear")
        assert "Cleared project memory" in clear_msg
        assert mem_file.read_text(encoding="utf-8") == ""


class TestCmdPlan:
    """``/plan [view|clear]`` — view or clear plan."""

    def test_plan_empty(self) -> None:
        plan = get_active_plan()
        plan.clear()
        msg = cmd_plan("view")
        assert "No active task plan" in msg

    def test_plan_view_and_clear(self) -> None:
        plan = get_active_plan()
        plan.set_tasks(["Step A", "Step B"])
        msg = cmd_plan("view")
        assert "Step A" in msg
        assert "Step B" in msg

        clear_msg = cmd_plan("clear")
        assert "Active task plan cleared" in clear_msg
        assert not plan.tasks


class TestCmdModel:
    """``/model [name]`` — show or switch model."""

    def test_model_show(self) -> None:
        msg, model = cmd_model("gpt-4o")
        assert "Current model: gpt-4o" in msg
        assert model == "gpt-4o"

    def test_model_switch_valid(self) -> None:
        with patch("agentsx.cli.commands.create_provider"):
            msg, model = cmd_model("gpt-4o", "claude-3-5-sonnet")
            assert "Model switched to 'claude-3-5-sonnet'" in msg
            assert model == "claude-3-5-sonnet"

    def test_model_switch_invalid(self) -> None:
        with patch(
            "agentsx.cli.commands.create_provider",
            side_effect=ValueError("Bad provider"),
        ):
            msg, model = cmd_model("gpt-4o", "invalid-model")
            assert "Error creating provider" in msg
            assert model == "gpt-4o"


class TestCmdStatus:
    """``/status`` — show session, model, context & workspace info."""

    def test_status_output(self, tmp_path: Path) -> None:
        messages = [
            AgentMessage(role=MessageRole.SYSTEM, content="system prompt"),
            AgentMessage(role=MessageRole.USER, content="hello world"),
        ]
        status_text = cmd_status(
            session_id="abcdef1234567890",
            model_name="gpt-4o",
            messages=messages,
            workspace_root=tmp_path,
        )
        assert "Session Status:" in status_text
        assert "abcdef123456..." in status_text
        assert "gpt-4o" in status_text
        assert "2 messages" in status_text
        assert str(tmp_path) in status_text
        assert "Git" in status_text
        assert "Plan" in status_text


class TestCmdHelp:
    """``/help`` — show help."""

    def test_help(self) -> None:
        text = cmd_help()
        assert "/sessions" in text
        assert "/status" in text
        assert "/model" in text
        assert "/memory" in text
        assert "/plan" in text
        assert "/verify" in text
        assert "/revert" in text
        assert "/help" in text
        assert "/exit" in text
