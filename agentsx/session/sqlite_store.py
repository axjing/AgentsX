"""SQLite session store with FTS5 full-text search.

Provides an alternative session backend to the JSONL file store.
Supports efficient cross-session search, session metadata queries,
and parent-child session chains for branching.

Usage::

    store = SQLiteSessionStore()
    session = store.create("gpt-4o", "My Chat")
    store.append(session.id, AgentMessage(...))
    results = store.search("function that reads files")
    store.close()

Design:
    - WAL mode for concurrent readers + single writer
    - FTS5 virtual table for fast text search
    - Parent session chains for branch tracking
    - Compatible with JSONL format for message content
"""

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from agentsx.config import get_settings
from agentsx.protocol.errors import SessionError
from agentsx.protocol.messages import AgentMessage, MessageRole, ToolCall
from agentsx.session.protocol import SessionBackend


@dataclass
class SQLiteSession:
    """Metadata for a single conversation session."""

    id: str
    created_at: datetime
    updated_at: datetime
    model_name: str
    title: str
    source: str = "cli"
    """Source tag: 'cli', 'telegram', 'discord', etc."""

    parent_session_id: str | None = None
    """Parent session for branches."""

    branch_reason: str | None = None
    """Reason for branching: 'user', 'compression', 'delegate', etc."""


class SQLiteSessionStore(SessionBackend):
    """SQLite-backed session storage with FTS5 search.

    Usage::

        store = SQLiteSessionStore()
        session = store.create("gpt-4o", "My Chat")
        store.append(session.id, AgentMessage(...))
        results = store.search("read file contents")
        store.close()
    """

    _SCHEMA_VERSION = 1

    _CREATE_TABLES = """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            model_name TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'cli',
            parent_session_id TEXT REFERENCES sessions(id),
            branch_reason TEXT,
            schema_version INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            tool_calls TEXT,
            tool_call_id TEXT,
            name TEXT,
            msg_index INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id, msg_index);

        CREATE TABLE IF NOT EXISTS compaction_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            replaces_ids TEXT NOT NULL,
            summary TEXT NOT NULL,
            token_estimate INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_compaction_session
            ON compaction_entries(session_id);

        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
            USING fts5(content, session_id, tokenize='porter unicode61');

        CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages
        BEGIN
            INSERT INTO messages_fts(rowid, content, session_id)
            VALUES (new.id, new.content, new.session_id);
        END;

        CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages
        BEGIN
            INSERT INTO messages_fts(messages_fts, rowid, content, session_id)
            VALUES ('delete', old.id, old.content, old.session_id);
        END;
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
    ) -> None:
        if db_path is None:
            settings = get_settings()
            base = Path(settings.session_dir or Path.home() / ".agentsx")
            db_path = base / "sessions.db"

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = self._init_db()

    @property
    def _db(self) -> sqlite3.Connection:
        """Return the active database connection."""
        if self._conn is None:
            raise SessionError("Session store is closed")
        return self._conn

    def _init_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        conn.executescript(self._CREATE_TABLES)
        conn.commit()
        return conn

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._db.close()
            self._conn = None

    def create(
        self,
        model_name: str,
        title: str = "",
        source: str = "cli",
        parent_id: str | None = None,
        branch_reason: str | None = None,
    ) -> SQLiteSession:
        """Create a new session.

        Args:
            model_name: The LLM model identifier.
            title: Optional human-readable title.
            source: Source tag ('cli', 'telegram', etc.).
            parent_id: Parent session for branches.
            branch_reason: Reason for branching.

        Returns:
            The newly created SQLiteSession.
        """
        session_id = uuid4().hex[:16]
        now = datetime.now(timezone.utc).isoformat()
        session = SQLiteSession(
            id=session_id,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
            model_name=model_name,
            title=title or f"Session {session_id[:8]}",
            source=source,
            parent_session_id=parent_id,
            branch_reason=branch_reason,
        )

        with self._lock:
            self._db.execute(
                "INSERT INTO sessions "
                "(id, created_at, updated_at, model_name, title, source, "
                "parent_session_id, branch_reason, schema_version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    now,
                    now,
                    model_name,
                    session.title,
                    source,
                    parent_id,
                    branch_reason,
                    self._SCHEMA_VERSION,
                ),
            )
            self._db.commit()
        return session

    def get(self, session_id: str) -> SQLiteSession:
        """Load session metadata by ID.

        Raises:
            SessionError: If the session does not exist.
        """
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()

        if row is None:
            msg = f"Session not found: {session_id}"
            raise SessionError(msg)

        return self._row_to_session(row)

    def get_messages(self, session_id: str) -> list[AgentMessage]:
        """Load all messages for a session, ordered by index."""
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY msg_index",
                (session_id,),
            ).fetchall()

        return [self._row_to_message(r) for r in rows]

    def append(self, session_id: str, message: AgentMessage) -> None:
        """Append a single message.

        Raises:
            SessionError: If the session does not exist.
        """
        with self._lock:
            exists = self._db.execute(
                "SELECT 1 FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if exists is None:
                msg = f"Session not found: {session_id}"
                raise SessionError(msg)

            idx = self._db.execute(
                "SELECT COALESCE(MAX(msg_index), -1) + 1 FROM messages "
                "WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]

            now = datetime.now(timezone.utc).isoformat()
            tool_calls_json = None
            if message.tool_calls:
                tool_calls_json = json.dumps(
                    [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in message.tool_calls
                    ]
                )

            self._db.execute(
                "INSERT INTO messages "
                "(session_id, role, content, tool_calls, tool_call_id, "
                "name, msg_index, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    message.role.value,
                    message.content,
                    tool_calls_json,
                    message.tool_call_id,
                    message.name,
                    idx,
                    now,
                ),
            )
            self._db.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            self._db.commit()

    def list_sessions(self, source: str | None = None) -> list[SQLiteSession]:
        """Return all sessions, newest first.

        Args:
            source: Filter by source tag (None = all).
        """
        with self._lock:
            if source:
                rows = self._db.execute(
                    "SELECT * FROM sessions WHERE source = ? ORDER BY created_at DESC",
                    (source,),
                ).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT * FROM sessions ORDER BY created_at DESC"
                ).fetchall()

        return [self._row_to_session(r) for r in rows]

    def delete(self, session_id: str) -> None:
        """Delete a session and all its messages.

        Raises:
            SessionError: If the session does not exist.
        """
        with self._lock:
            exists = self._db.execute(
                "SELECT 1 FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if exists is None:
                msg = f"Session not found: {session_id}"
                raise SessionError(msg)

            self._db.execute(
                "DELETE FROM messages WHERE session_id = ?",
                (session_id,),
            )
            self._db.execute(
                "DELETE FROM sessions WHERE id = ?",
                (session_id,),
            )
            self._db.commit()

    def branch(
        self,
        session_id: str,
        title: str = "",
        reason: str = "user",
        from_message_index: int | None = None,
    ) -> SQLiteSession:
        """Create a branched session inheriting message history.

        Args:
            session_id: Source session.
            title: Optional title.
            reason: Branch reason ('user', 'compression', 'delegate').
            from_message_index: Copy only messages up to this index.

        Returns:
            The new branched session.
        """
        source = self.get(session_id)
        messages = self.get_messages(session_id)
        if from_message_index is not None:
            messages = messages[:from_message_index]

        new = self.create(
            model_name=source.model_name,
            title=title or f"Branch of {source.title}",
            source=source.source,
            parent_id=session_id,
            branch_reason=reason,
        )

        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            for idx, msg in enumerate(messages):
                tool_calls_json = None
                if msg.tool_calls:
                    tool_calls_json = json.dumps(
                        [
                            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                            for tc in msg.tool_calls
                        ]
                    )
                self._db.execute(
                    "INSERT INTO messages "
                    "(session_id, role, content, tool_calls, tool_call_id, "
                    "name, msg_index, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        new.id,
                        msg.role.value,
                        msg.content,
                        tool_calls_json,
                        msg.tool_call_id,
                        msg.name,
                        idx,
                        now,
                    ),
                )
            self._db.commit()
        return new

    def search(
        self,
        query: str,
        source: str | None = None,
        limit: int = 20,
    ) -> list[tuple[str, str, int]]:
        """Full-text search across all session messages.

        Args:
            query: FTS5 search query (supports FTS5 syntax).
            source: Filter by source tag.
            limit: Maximum results.

        Returns:
            List of (session_id, snippet, rank) tuples.
        """
        fts_query = query
        if source:
            fts_query = f"{query} AND session_id IN "
            with self._lock:
                ids = self._db.execute(
                    "SELECT id FROM sessions WHERE source = ?",
                    (source,),
                ).fetchall()
            if not ids:
                return []
            id_list = ",".join(f"'{r[0]}'" for r in ids)
            fts_query += f"({id_list})"

        with self._lock:
            rows = self._db.execute(
                "SELECT s.id, snippet(messages_fts, -1, '...', '...', '...', 32), "
                "rank FROM messages_fts AS m "
                "JOIN sessions AS s ON s.id = m.session_id "
                "WHERE messages_fts MATCH ? "
                "ORDER BY rank LIMIT ?",
                (fts_query, limit),
            ).fetchall()

        return [(r[0], r[1], r[2]) for r in rows]

    def update_title(self, session_id: str, title: str) -> SQLiteSession:
        """Update the session title.

        Raises:
            SessionError: If the session does not exist.
        """
        with self._lock:
            exists = self._db.execute(
                "SELECT 1 FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if exists is None:
                msg = f"Session not found: {session_id}"
                raise SessionError(msg)

            self._db.execute(
                "UPDATE sessions SET title = ? WHERE id = ?",
                (title, session_id),
            )
            self._db.commit()
        return self.get(session_id)

    # ── Internal helpers ────────────────────────────────────────────────

    def _row_to_session(self, row: sqlite3.Row) -> SQLiteSession:
        return SQLiteSession(
            id=row["id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            model_name=row["model_name"],
            title=row["title"],
            source=row["source"],
            parent_session_id=row["parent_session_id"],
            branch_reason=row["branch_reason"],
        )

    def _row_to_message(self, row: sqlite3.Row) -> AgentMessage:
        tool_calls: list[ToolCall] | None = None
        raw_calls = row["tool_calls"]
        if raw_calls:
            tool_calls = [
                ToolCall(
                    id=tc["id"],
                    name=tc["name"],
                    arguments=tc["arguments"],
                )
                for tc in json.loads(raw_calls)
            ]

        return AgentMessage(
            role=MessageRole(row["role"]),
            content=row["content"],
            id=f"msg_{row['id']}",
            tool_calls=tool_calls,
            tool_call_id=row["tool_call_id"],
            name=row["name"],
        )

    def append_compaction_entry(
        self,
        session_id: str,
        replaces_ids: list[str],
        summary: str,
        token_estimate: int = 0,
    ) -> None:
        """Record a compaction entry without modifying messages.

        Args:
            session_id: The session to record compaction for.
            replaces_ids: Message IDs being replaced.
            summary: Summary of the compacted messages.
            token_estimate: Token count of replaced messages.

        Raises:
            SessionError: If the session does not exist.
        """
        with self._lock:
            exists = self._db.execute(
                "SELECT 1 FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if exists is None:
                msg = f"Session not found: {session_id}"
                raise SessionError(msg)

            now = datetime.now(timezone.utc).isoformat()
            self._db.execute(
                "INSERT INTO compaction_entries "
                "(session_id, replaces_ids, summary, token_estimate, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    session_id,
                    json.dumps(replaces_ids),
                    summary,
                    token_estimate,
                    now,
                ),
            )
            self._db.commit()

    def get_compaction_entries(
        self,
        session_id: str,
    ) -> list[tuple[list[str], str, int]]:
        """Load all compaction entries for a session.

        Args:
            session_id: The session to query.

        Returns:
            List of (replaces_ids, summary, token_estimate) tuples.
        """
        with self._lock:
            rows = self._db.execute(
                "SELECT replaces_ids, summary, token_estimate "
                "FROM compaction_entries WHERE session_id = ? "
                "ORDER BY id",
                (session_id,),
            ).fetchall()

        return [
            (json.loads(r["replaces_ids"]), r["summary"], r["token_estimate"])
            for r in rows
        ]
