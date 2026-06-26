"""Session storage — JSONL file tree with memory cache.

Structure::

    ~/.agentsx/sessions/
    └── <session_id>/
        ├── meta.json           # Session metadata (JSON)
        └── messages.jsonl      # One AgentMessage per line (JSON, append-only)

Design:
    - Zero external dependencies
    - Append-only O(1) writes (no locking needed)
    - Memory cache for active sessions
    - grep-friendly plain text
    - Branch = copy files + new meta
    - No database, no migrations
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from agentsx.config import get_settings
from agentsx.core.errors import SessionError
from agentsx.core.types import AgentMessage, MessageRole, ToolCall


@dataclass
class Session:
    """Metadata for a single conversation session."""

    id: str
    created_at: datetime
    updated_at: datetime
    model_name: str
    title: str


class SessionStore:
    """JSONL file-tree session storage with memory cache.

    Usage::

        store = SessionStore()
        session = store.create("gpt-4o", "My Chat")
        store.append(session.id, AgentMessage(role=MessageRole.USER, content="Hi"))
        messages = store.get_messages(session.id)
    """

    def __init__(
        self,
        base_dir: str | Path | None = None,
        cache_size: int = 10,
    ) -> None:
        if base_dir is None:
            settings = get_settings()
            base_dir = settings.session_dir or Path.home() / ".agentsx" / "sessions"
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._cache_size = cache_size
        self._message_cache: dict[str, list[AgentMessage]] = {}
        self._pending_timestamps: dict[str, str] = {}

    # ── Public API ─────────────────────────────────────────────────────

    def create(self, model_name: str, title: str = "") -> Session:
        """Create a new session directory with metadata.

        Args:
            model_name: The LLM model identifier used for this session.
            title: Optional human-readable title.

        Returns:
            The newly created Session.
        """
        session_id = uuid4().hex[:16]
        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True)

        now = datetime.now(timezone.utc)
        session = Session(
            id=session_id,
            created_at=now,
            updated_at=now,
            model_name=model_name,
            title=title or f"Session {session_id[:8]}",
        )
        self._write_meta(session)
        self._message_cache[session_id] = []
        return session

    def get(self, session_id: str) -> Session:
        """Load session metadata by ID.

        Raises:
            SessionError: If the session does not exist.
        """
        meta_path = self._session_dir(session_id) / "meta.json"
        if not meta_path.is_file():
            msg = f"Session not found: {session_id}"
            raise SessionError(msg)
        with open(meta_path, encoding="utf-8") as f:
            return _deserialize_session(json.load(f))

    def get_messages(self, session_id: str) -> list[AgentMessage]:
        """Load all messages for a session.

        Uses memory cache when available; falls back to disk read.
        """
        if session_id in self._message_cache:
            return list(self._message_cache[session_id])

        path = self._session_dir(session_id) / "messages.jsonl"
        if not path.is_file():
            return []
        messages: list[AgentMessage] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    messages.append(_deserialize_message(json.loads(stripped)))
        # Populate cache
        self._message_cache[session_id] = messages
        self._evict_cache()
        return messages

    def append(self, session_id: str, message: AgentMessage) -> None:
        """Append a single message to the session log.

        The session's ``updated_at`` timestamp is refreshed after each append.

        Raises:
            SessionError: If the session does not exist.
        """
        session_dir = self._session_dir(session_id)
        if not session_dir.is_dir():
            msg = f"Session not found: {session_id}"
            raise SessionError(msg)
        line = _serialize_message(message)
        with open(session_dir / "messages.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")
        # Update cache
        if session_id in self._message_cache:
            self._message_cache[session_id].append(message)
        self._update_timestamp(session_id)

    def list(self) -> list[Session]:
        """Return all sessions, newest first.

        Corrupt sessions (missing or malformed meta.json) are silently skipped.
        """
        if not self.base_dir.is_dir():
            return []
        sessions: list[Session] = []
        for entry in sorted(self.base_dir.iterdir()):
            meta_path = entry / "meta.json"
            if meta_path.is_file():
                try:
                    with open(meta_path, encoding="utf-8") as f:
                        sessions.append(_deserialize_session(json.load(f)))
                except (json.JSONDecodeError, KeyError):
                    continue
        sessions.sort(key=lambda s: s.created_at, reverse=True)
        return sessions

    def delete(self, session_id: str) -> None:
        """Permanently delete a session and all its data.

        Raises:
            SessionError: If the session does not exist.
        """
        session_dir = self._session_dir(session_id)
        if not session_dir.is_dir():
            msg = f"Session not found: {session_id}"
            raise SessionError(msg)
        shutil.rmtree(session_dir)
        self._message_cache.pop(session_id, None)

    def branch(
        self,
        session_id: str,
        title: str = "",
        from_message_index: int | None = None,
    ) -> Session:
        """Create a new session that inherits message history.

        Args:
            session_id: Source session to branch from.
            title: Optional title for the new session.
            from_message_index: If set, only copy messages up to this
                index (exclusive).  ``None`` copies all messages.

        Returns:
            The newly branched Session.
        """
        source = self.get(session_id)
        new_id = uuid4().hex[:16]
        new_dir = self._session_dir(new_id)
        source_dir = self._session_dir(session_id)

        new_dir.mkdir(parents=True)
        source_msgs = source_dir / "messages.jsonl"

        if from_message_index is not None and from_message_index > 0:
            # Copy only up to the specified message index
            source_messages = self.get_messages(session_id)
            branch_msgs = source_messages[:from_message_index]
            target_path = new_dir / "messages.jsonl"
            with open(target_path, "w", encoding="utf-8") as f:
                for msg in branch_msgs:
                    f.write(_serialize_message(msg) + "\n")
            self._message_cache[new_id] = list(branch_msgs)
        elif source_msgs.is_file():
            shutil.copy(source_msgs, new_dir / "messages.jsonl")

        now = datetime.now(timezone.utc)
        session = Session(
            id=new_id,
            created_at=now,
            updated_at=now,
            model_name=source.model_name,
            title=title or f"Branch of {source.title}",
        )
        self._write_meta(session)
        self._evict_cache()
        return session

    # ── Internals ──────────────────────────────────────────────────────

    def _session_dir(self, session_id: str) -> Path:
        return self.base_dir / session_id

    def _write_meta(self, session: Session) -> None:
        # Flush any pending timestamps for this session before overwriting meta
        self._pending_timestamps.pop(session.id, None)
        self._flush_timestamps()
        data: dict[str, object] = {
            "id": session.id,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "model_name": session.model_name,
            "title": session.title,
        }
        path = self._session_dir(session.id) / "meta.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _update_timestamp(self, session_id: str) -> None:
        """Defer timestamp update to avoid read-modify-write race.

        The timestamp is stored in memory and flushed to disk when
        another write (_write_meta or _flush_timestamps) occurs.
        """
        self._pending_timestamps[session_id] = datetime.now(timezone.utc).isoformat()

    def _flush_timestamps(self) -> None:
        """Write all pending timestamps to meta.json files.

        Each file is read-once, updated, and written atomically
        to avoid the previous read-modify-write race.
        """
        for sid, ts in self._pending_timestamps.items():
            meta_path = self._session_dir(sid) / "meta.json"
            if not meta_path.is_file():
                continue
            with open(meta_path, encoding="utf-8") as f:
                data = json.load(f)
            data["updated_at"] = ts
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        self._pending_timestamps.clear()

    def _evict_cache(self) -> None:
        """Remove oldest cached sessions if cache is full."""
        if len(self._message_cache) > self._cache_size:
            # Evict the first cached session (LRU simple eviction)
            evict_id = next(iter(self._message_cache))
            self._message_cache.pop(evict_id, None)


# ── Serialisation helpers ──────────────────────────────────────────────


def _serialize_message(msg: AgentMessage) -> str:
    """Serialize an AgentMessage to a JSON string (one line)."""
    data: dict[str, Any] = {
        "role": msg.role.value,
        "content": msg.content,
        "id": msg.id,
    }
    if msg.tool_calls:
        data["tool_calls"] = [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            for tc in msg.tool_calls
        ]
    if msg.tool_call_id:
        data["tool_call_id"] = msg.tool_call_id
    if msg.name:
        data["name"] = msg.name
    return json.dumps(data, separators=(",", ":"))


def _deserialize_message(data: dict[str, Any]) -> AgentMessage:
    """Reconstruct an AgentMessage from a parsed JSON dict."""
    tool_calls: list[ToolCall] | None = None
    raw_calls = data.get("tool_calls")
    if raw_calls:
        tool_calls = [
            ToolCall(
                id=tc.get("id", ""),
                name=tc.get("name", ""),
                arguments=tc.get("arguments", {}),
            )
            for tc in raw_calls
        ]
    return AgentMessage(
        role=MessageRole(data.get("role", "")),
        content=data.get("content", ""),
        id=data.get("id", ""),
        tool_calls=tool_calls,
        tool_call_id=data.get("tool_call_id"),
        name=data.get("name"),
    )


def _deserialize_session(data: dict[str, Any]) -> Session:
    """Reconstruct a Session from a parsed meta.json dict."""
    now_iso = datetime.now(timezone.utc).isoformat()
    return Session(
        id=data.get("id", ""),
        created_at=datetime.fromisoformat(
            data.get("created_at", now_iso),
        ),
        updated_at=datetime.fromisoformat(
            data.get("updated_at", now_iso),
        ),
        model_name=data.get("model_name", ""),
        title=data.get("title", ""),
    )
