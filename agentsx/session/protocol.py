"""SessionBackend Protocol — the interface that all session stores implement.

Provides a single typed contract for session storage backends so that
components like ``AgentHarness`` can depend on the Protocol rather than
a concrete class.
"""

from __future__ import annotations

from typing import Any, Protocol


class SessionBackend(Protocol):
    """Abstract interface for session storage backends.

    Both ``SessionStore`` (JSONL file tree) and ``SQLiteSessionStore``
    (SQLite with FTS5) implement this Protocol.
    """

    def create(self, model_name: str, title: str = "") -> Any:
        """Create a new session and return its metadata."""
        ...

    def get(self, session_id: str) -> Any:
        """Load session metadata by ID."""
        ...

    def get_messages(self, session_id: str) -> list:
        """Load all messages for a session."""
        ...

    def append(self, session_id: str, message: Any) -> None:
        """Append a single message to the session."""
        ...

    def list_sessions(self) -> list:
        """Return all sessions, newest first."""
        ...

    def delete(self, session_id: str) -> None:
        """Permanently delete a session and all its data."""
        ...

    def branch(
        self,
        session_id: str,
        title: str = "",
        from_message_index: int | None = None,
    ) -> Any:
        """Create a new session that inherits message history."""
        ...

    def update_title(self, session_id: str, title: str) -> Any:
        """Update the title of a session."""
        ...

    def append_compaction_entry(
        self,
        session_id: str,
        replaces_ids: list[str],
        summary: str,
        token_estimate: int = 0,
    ) -> None:
        """Record a compaction entry without modifying messages."""
        ...

    def close(self) -> None:
        """Close the backend / release resources."""
        ...
