"""Tests for SQLite session store with FTS5 (``agentsx/session/sqlite_store.py``)."""

import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from agentsx.protocol.errors import SessionError
from agentsx.protocol.messages import AgentMessage, MessageRole, ToolCall
from agentsx.session import create_session_store
from agentsx.session.sqlite_store import SQLiteSession, SQLiteSessionStore


@pytest.fixture
def store() -> Generator[SQLiteSessionStore, None, None]:
    """Create a temporary SQLite session store."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_sessions.db"
        s = SQLiteSessionStore(db_path=db_path)
        yield s
        s.close()


class TestSQLiteSessionStoreLifecycle:
    """Session creation, retrieval, listing, deletion, and close."""

    def test_create_and_get(self, store: SQLiteSessionStore) -> None:
        sess = store.create("gpt-4o", title="Test Chat", source="test-suite")
        assert isinstance(sess, SQLiteSession)
        assert sess.model_name == "gpt-4o"
        assert sess.title == "Test Chat"
        assert sess.source == "test-suite"
        assert sess.parent_session_id is None

        fetched = store.get(sess.id)
        assert fetched.id == sess.id
        assert fetched.title == sess.title
        assert fetched.model_name == sess.model_name

    def test_get_nonexistent_raises(self, store: SQLiteSessionStore) -> None:
        with pytest.raises(SessionError, match="Session not found"):
            store.get("nonexistent-id")

    def test_list_sessions(self, store: SQLiteSessionStore) -> None:
        s1 = store.create("model-1", "First")
        s2 = store.create("model-2", "Second")

        sessions = store.list_sessions()
        assert len(sessions) == 2
        # Ordered by updated_at descending
        assert sessions[0].id == s2.id
        assert sessions[1].id == s1.id

    def test_update_title(self, store: SQLiteSessionStore) -> None:
        sess = store.create("gpt-4o", "Old Title")
        updated = store.update_title(sess.id, "New Title")
        assert updated.title == "New Title"
        assert store.get(sess.id).title == "New Title"

    def test_update_title_nonexistent(self, store: SQLiteSessionStore) -> None:
        with pytest.raises(SessionError, match="Session not found"):
            store.update_title("bad-id", "Title")

    def test_delete_session(self, store: SQLiteSessionStore) -> None:
        sess = store.create("gpt-4o", "To Delete")
        store.append(sess.id, AgentMessage(role=MessageRole.USER, content="Hello"))
        store.delete(sess.id)

        with pytest.raises(SessionError):
            store.get(sess.id)
        assert store.get_messages(sess.id) == []

    def test_operations_after_close_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "closed.db"
            store = SQLiteSessionStore(db_path=db_path)
            store.close()
            with pytest.raises(SessionError, match="Session store is closed"):
                store.create("gpt-4o")


class TestSQLiteMessagesAndSearch:
    """Message persistence and FTS5 full-text search."""

    def test_append_and_get_messages(self, store: SQLiteSessionStore) -> None:
        sess = store.create("gpt-4o", "Chat")
        m1 = AgentMessage(role=MessageRole.USER, content="How do I read a file?")
        m2 = AgentMessage(
            role=MessageRole.ASSISTANT,
            content="Use pathlib or open.",
            tool_calls=[
                ToolCall(id="tc1", name="tool_file_read", arguments={"path": "a.txt"})
            ],
        )
        store.append(sess.id, m1)
        store.append(sess.id, m2)

        messages = store.get_messages(sess.id)
        assert len(messages) == 2
        assert messages[0].role == MessageRole.USER
        assert messages[0].content == "How do I read a file?"
        assert messages[1].role == MessageRole.ASSISTANT
        assert messages[1].tool_calls is not None
        assert messages[1].tool_calls[0].name == "tool_file_read"

    def test_fts5_search(self, store: SQLiteSessionStore) -> None:
        s1 = store.create("gpt-4o", "Session A", source="cli")
        s2 = store.create("gpt-4o", "Session B", source="web")

        store.append(
            s1.id,
            AgentMessage(role=MessageRole.USER, content="Quantum computing algorithms"),
        )
        store.append(
            s2.id,
            AgentMessage(role=MessageRole.USER, content="Classical sorting algorithms"),
        )

        # Search for 'quantum'
        results = store.search("quantum")
        assert len(results) == 1
        assert results[0][0] == s1.id
        assert "Quantum" in results[0][1] or "quantum" in results[0][1]

        # Search with source filter
        results_cli = store.search("algorithms", source="cli")
        assert len(results_cli) == 1
        assert results_cli[0][0] == s1.id

        results_web = store.search("algorithms", source="web")
        assert len(results_web) == 1
        assert results_web[0][0] == s2.id

    def test_fts5_no_matches(self, store: SQLiteSessionStore) -> None:
        sess = store.create("gpt-4o", "Chat")
        store.append(
            sess.id, AgentMessage(role=MessageRole.USER, content="Hello world")
        )
        results = store.search("supercalifragilistic")
        assert results == []


class TestSQLiteBranching:
    """Session branching and message history inheritance."""

    def test_full_branch(self, store: SQLiteSessionStore) -> None:
        parent = store.create("gpt-4o", "Parent")
        store.append(parent.id, AgentMessage(role=MessageRole.USER, content="Step 1"))
        store.append(
            parent.id, AgentMessage(role=MessageRole.ASSISTANT, content="Step 2")
        )

        child = store.branch(parent.id, title="Child Branch", reason="experiment")
        assert child.parent_session_id == parent.id
        assert child.branch_reason == "experiment"
        assert child.title == "Child Branch"

        child_msgs = store.get_messages(child.id)
        assert len(child_msgs) == 2
        assert child_msgs[0].content == "Step 1"
        assert child_msgs[1].content == "Step 2"

    def test_partial_branch(self, store: SQLiteSessionStore) -> None:
        parent = store.create("gpt-4o", "Parent")
        for i in range(5):
            store.append(
                parent.id, AgentMessage(role=MessageRole.USER, content=f"Msg {i}")
            )

        # Only copy up to index 2 (messages 0, 1)
        child = store.branch(parent.id, from_message_index=2)
        child_msgs = store.get_messages(child.id)
        assert len(child_msgs) == 2
        assert child_msgs[0].content == "Msg 0"
        assert child_msgs[1].content == "Msg 1"


class TestSQLiteCompactionEntries:
    """Append-only compaction audit logging in SQLite."""

    def test_compaction_entry_lifecycle(self, store: SQLiteSessionStore) -> None:
        sess = store.create("gpt-4o", "Compaction Test")
        store.append_compaction_entry(
            sess.id,
            replaces_ids=["msg_1", "msg_2"],
            summary="User asked about weather",
            token_estimate=120,
        )

        entries = store.get_compaction_entries(sess.id)
        assert len(entries) == 1
        replaces_ids, summary, tokens = entries[0]
        assert replaces_ids == ["msg_1", "msg_2"]
        assert summary == "User asked about weather"
        assert tokens == 120

    def test_compaction_entry_nonexistent_session(
        self, store: SQLiteSessionStore
    ) -> None:
        with pytest.raises(SessionError, match="Session not found"):
            store.append_compaction_entry("bad-id", ["1"], "summary")


class TestSQLiteFactory:
    """Test create_session_store factory with sqlite backend."""

    def test_factory_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "factory.db"
            backend = create_session_store("sqlite", db_path=db_path)
            assert isinstance(backend, SQLiteSessionStore)
            sess = backend.create("gpt-4o", "Factory Chat")
            assert backend.get(sess.id).title == "Factory Chat"
            backend.close()
