"""Session storage.

Two backends available:

- ``SessionStore``: JSONL file tree with memory cache (default).
  Zero external dependencies, append-only O(1) writes.

- ``SQLiteSessionStore``: SQLite-backed with FTS5 full-text search.
  Supports cross-session search, parent-child branch chains, and
  source tagging. Import explicitly when needed.
"""

from agentsx.session.store import Session, SessionStore

__all__ = ["Session", "SessionStore"]


def create_sqlite_store(
    db_path: str | None = None,
) -> "agentsx.session.sqlite_store.SQLiteSessionStore":
    """Factory for SQLite session store with FTS5 search.

    Args:
        db_path: Path to SQLite database file.
            Defaults to ``~/.agentsx/sessions.db``.

    Returns:
        A configured ``SQLiteSessionStore`` instance.

    Example::

        from agentsx.session import create_sqlite_store
        store = create_sqlite_store()
        results = store.search("function that reads files")
    """
    from agentsx.session.sqlite_store import SQLiteSessionStore

    return SQLiteSessionStore(db_path=db_path)


# Lazy import reference for type annotations.
import agentsx.session.sqlite_store  # noqa: E402, F401
