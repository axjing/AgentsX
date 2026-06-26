"""Tests for session storage (``agentsx/session.py``)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentsx.core.errors import SessionError
from agentsx.core.types import AgentMessage, MessageRole, ToolCall
from agentsx.session import Session, SessionStore


class TestSession:
    """Session dataclass construction."""

    def test_basic(self) -> None:
        now = datetime.now(timezone.utc)
        s = Session(
            id="abc",
            created_at=now,
            updated_at=now,
            model_name="gpt-4o",
            title="test",
        )
        assert s.id == "abc"
        assert s.model_name == "gpt-4o"
        assert s.title == "test"

    def test_title_defaults_to_empty(self) -> None:
        now = datetime.now(timezone.utc)
        s = Session(
            id="x",
            created_at=now,
            updated_at=now,
            model_name="claude",
            title="",
        )
        assert s.title == ""


class TestSessionStore:
    """SessionStore — CRUD and edge-case tests using tmp_path."""

    # ── Fixtures ─────────────────────────────────────────────────────

    @pytest.fixture
    def store(self, tmp_path: Path) -> SessionStore:
        return SessionStore(base_dir=tmp_path / "sessions")

    # ── Create ───────────────────────────────────────────────────────

    def test_create(self, store: SessionStore) -> None:
        session = store.create(model_name="gpt-4o")
        assert session.id
        assert session.model_name == "gpt-4o"
        assert session.title.startswith("Session ")
        assert (store.base_dir / session.id / "meta.json").is_file()

    def test_create_with_title(self, store: SessionStore) -> None:
        session = store.create(model_name="claude", title="My Chat")
        assert session.title == "My Chat"

    def test_create_unique_ids(self, store: SessionStore) -> None:
        s1 = store.create("gpt-4o")
        s2 = store.create("gpt-4o")
        assert s1.id != s2.id

    def test_create_sets_timestamps(self, store: SessionStore) -> None:
        before = datetime.now(timezone.utc)
        session = store.create("gpt-4o")
        after = datetime.now(timezone.utc)
        assert before <= session.created_at <= after
        assert session.updated_at == session.created_at

    # ── Get ──────────────────────────────────────────────────────────

    def test_get(self, store: SessionStore) -> None:
        created = store.create(model_name="gpt-4o")
        loaded = store.get(created.id)
        assert loaded.id == created.id
        assert loaded.model_name == "gpt-4o"
        assert loaded.title == created.title

    def test_get_not_found(self, store: SessionStore) -> None:
        with pytest.raises(SessionError, match="not found"):
            store.get("nonexistent")

    # ── Append & Get Messages ────────────────────────────────────────

    def test_append_and_get_messages(self, store: SessionStore) -> None:
        session = store.create(model_name="gpt-4o")
        msg = AgentMessage(role=MessageRole.USER, content="Hello")
        store.append(session.id, msg)
        messages = store.get_messages(session.id)
        assert len(messages) == 1
        assert messages[0].role == MessageRole.USER
        assert messages[0].content == "Hello"

    def test_append_multiple_messages(self, store: SessionStore) -> None:
        session = store.create("gpt-4o")
        store.append(session.id, AgentMessage(role=MessageRole.USER, content="Hi"))
        store.append(
            session.id,
            AgentMessage(role=MessageRole.ASSISTANT, content="Hello!"),
        )
        messages = store.get_messages(session.id)
        assert len(messages) == 2
        assert messages[0].role == MessageRole.USER
        assert messages[1].role == MessageRole.ASSISTANT

    def test_append_system_message(self, store: SessionStore) -> None:
        session = store.create("gpt-4o")
        msg = AgentMessage(role=MessageRole.SYSTEM, content="You are a bot.")
        store.append(session.id, msg)
        messages = store.get_messages(session.id)
        assert messages[0].role == MessageRole.SYSTEM

    def test_append_with_tool_calls(self, store: SessionStore) -> None:
        session = store.create("gpt-4o")
        msg = AgentMessage(
            role=MessageRole.ASSISTANT,
            content="Let me check",
            tool_calls=[
                ToolCall(id="tc1", name="read", arguments={"path": "/tmp/a.txt"}),
                ToolCall(id="tc2", name="grep", arguments={"pattern": "foo"}),
            ],
        )
        store.append(session.id, msg)
        messages = store.get_messages(session.id)
        assert len(messages) == 1
        assert messages[0].tool_calls is not None
        assert len(messages[0].tool_calls) == 2
        assert messages[0].tool_calls[0].name == "read"
        assert messages[0].tool_calls[1].name == "grep"
        assert messages[0].tool_calls[0].arguments == {"path": "/tmp/a.txt"}

    def test_append_tool_result(self, store: SessionStore) -> None:
        session = store.create("gpt-4o")
        msg = AgentMessage(
            role=MessageRole.TOOL,
            content="file content here",
            tool_call_id="tc1",
            name="read",
        )
        store.append(session.id, msg)
        messages = store.get_messages(session.id)
        assert messages[0].tool_call_id == "tc1"
        assert messages[0].name == "read"
        assert messages[0].content == "file content here"

    def test_append_not_found(self, store: SessionStore) -> None:
        msg = AgentMessage(role=MessageRole.USER, content="Hi")
        with pytest.raises(SessionError, match="not found"):
            store.append("nonexistent", msg)

    def test_get_messages_empty(self, store: SessionStore) -> None:
        session = store.create("gpt-4o")
        assert store.get_messages(session.id) == []

    # ── Updated-at timestamp ─────────────────────────────────────────

    def test_append_updates_timestamp(self, store: SessionStore) -> None:
        session = store.create("gpt-4o")
        created_updated = session.updated_at
        store.append(session.id, AgentMessage(role=MessageRole.USER, content="Hi"))
        reloaded = store.get(session.id)
        assert reloaded.updated_at >= created_updated

    # ── List ─────────────────────────────────────────────────────────

    def test_list_empty(self, store: SessionStore) -> None:
        assert store.list() == []

    def test_list_multiple(self, store: SessionStore) -> None:
        store.create("model-a", "Chat 1")
        store.create("model-b", "Chat 2")
        all_sessions = store.list()
        assert len(all_sessions) >= 2
        assert all_sessions[0].created_at >= all_sessions[-1].created_at

    def test_list_skips_corrupt(self, store: SessionStore) -> None:
        store.create("gpt-4o", "Good")
        bad_dir = store.base_dir / "bad_session"
        bad_dir.mkdir()
        bad_dir.joinpath("meta.json").write_text("not-json", encoding="utf-8")
        all_sessions = store.list()
        assert len(all_sessions) == 1
        assert all_sessions[0].title == "Good"

    # ── Delete ───────────────────────────────────────────────────────

    def test_delete(self, store: SessionStore) -> None:
        session = store.create("gpt-4o")
        store.delete(session.id)
        assert not (store.base_dir / session.id).is_dir()
        with pytest.raises(SessionError, match="not found"):
            store.get(session.id)

    def test_delete_not_found(self, store: SessionStore) -> None:
        with pytest.raises(SessionError, match="not found"):
            store.delete("nonexistent")

    def test_delete_removes_messages_too(self, store: SessionStore) -> None:
        session = store.create("gpt-4o")
        store.append(session.id, AgentMessage(role=MessageRole.USER, content="Hi"))
        store.delete(session.id)
        assert not (store.base_dir / session.id).is_dir()

    # ── Branch ───────────────────────────────────────────────────────

    def test_branch_basic(self, store: SessionStore) -> None:
        s1 = store.create("gpt-4o", "Original")
        store.append(s1.id, AgentMessage(role=MessageRole.USER, content="Hello"))
        store.append(s1.id, AgentMessage(role=MessageRole.ASSISTANT, content="World"))
        s2 = store.branch(s1.id, "Fork")
        assert s2.id != s1.id
        assert s2.title == "Fork"
        msgs = store.get_messages(s2.id)
        assert len(msgs) == 2
        assert msgs[0].content == "Hello"
        assert msgs[1].content == "World"

    def test_branch_empty_session(self, store: SessionStore) -> None:
        s1 = store.create("gpt-4o")
        s2 = store.branch(s1.id, "Empty fork")
        assert s2.id != s1.id
        assert store.get_messages(s2.id) == []

    def test_branch_original_unchanged(self, store: SessionStore) -> None:
        s1 = store.create("gpt-4o")
        store.append(s1.id, AgentMessage(role=MessageRole.USER, content="Hi"))
        s2 = store.branch(s1.id)
        store.append(s1.id, AgentMessage(role=MessageRole.ASSISTANT, content="Reply"))
        assert len(store.get_messages(s1.id)) == 2
        assert len(store.get_messages(s2.id)) == 1

    def test_branch_from_index(self, store: SessionStore) -> None:
        s1 = store.create("gpt-4o", "Original")
        store.append(s1.id, AgentMessage(role=MessageRole.USER, content="A"))
        store.append(s1.id, AgentMessage(role=MessageRole.ASSISTANT, content="B"))
        store.append(s1.id, AgentMessage(role=MessageRole.USER, content="C"))
        s2 = store.branch(s1.id, "Partial fork", from_message_index=2)
        msgs = store.get_messages(s2.id)
        assert len(msgs) == 2
        assert msgs[0].content == "A"
        assert msgs[1].content == "B"

    # ── Round-trip fidelity ──────────────────────────────────────────

    def test_round_trip_preserves_all_fields(self, store: SessionStore) -> None:
        session = store.create("gpt-4o")
        original = AgentMessage(
            role=MessageRole.ASSISTANT,
            content="Let me search",
            tool_calls=[
                ToolCall(id="tc_1", name="web_search", arguments={"q": "weather"}),
            ],
            name="assistant",
        )
        store.append(session.id, original)
        loaded = store.get_messages(session.id)[0]
        assert loaded.role == original.role
        assert loaded.content == original.content
        assert loaded.id == original.id
        assert loaded.name == original.name
        assert loaded.tool_calls is not None
        assert loaded.tool_calls[0].id == "tc_1"
        assert loaded.tool_calls[0].name == "web_search"
        assert loaded.tool_calls[0].arguments == {"q": "weather"}

    # ── Cache layer ──────────────────────────────────────────────────

    def test_cache_populates_on_get(self, store: SessionStore) -> None:
        session = store.create("gpt-4o")
        store.append(session.id, AgentMessage(role=MessageRole.USER, content="Hi"))
        # First get reads from disk, populates cache
        msgs1 = store.get_messages(session.id)
        assert len(msgs1) == 1
        # Second get returns from cache (same data)
        msgs2 = store.get_messages(session.id)
        assert len(msgs2) == 1
        assert msgs2[0].content == "Hi"

    def test_append_updates_cache(self, store: SessionStore) -> None:
        session = store.create("gpt-4o")
        store.get_messages(session.id)  # populate empty cache
        store.append(session.id, AgentMessage(role=MessageRole.USER, content="Test"))
        msgs = store.get_messages(session.id)
        assert len(msgs) == 1
        assert msgs[0].content == "Test"
