"""Session storage.

Two backends available:

- ``SessionStore``: JSONL file tree with memory cache (default).
  Zero external dependencies, append-only O(1) writes.

- ``SQLiteSessionStore``: SQLite-backed with FTS5 full-text search.
  Supports cross-session search, parent-child branch chains, and
  source tagging. Import explicitly when needed.

The ``SessionBackend`` Protocol defines the common interface that all
backends implement, and ``create_session_store()`` is a factory that
instantiates the chosen backend by name.

Additionally, ``SessionSnapshot`` provides file-state capture and
rollback for safe context compaction.
"""

from agentsx.session.protocol import SessionBackend
from agentsx.session.snapshot import FileSnapshot, SessionSnapshot
from agentsx.session.store import Session, SessionStore

__all__ = [
    "FileSnapshot",
    "Session",
    "SessionBackend",
    "SessionSnapshot",
    "SessionStore",
    "create_session_store",
]


def create_session_store(backend: str = "jsonl", **kwargs) -> SessionBackend:
    """Factory for session storage backends.

    Args:
        backend: Backend name — ``"jsonl"`` (default) or ``"sqlite"``.
        **kwargs: Passed through to the backend constructor.

    Returns:
        A configured session store implementing ``SessionBackend``.

    Raises:
        ValueError: If the backend name is not recognised.

    Example::

        from agentsx.session import create_session_store
        store = create_session_store("jsonl")
        store = create_session_store("sqlite")
    """
    if backend == "jsonl":
        return SessionStore(**kwargs)
    if backend == "sqlite":
        from agentsx.session.sqlite_store import SQLiteSessionStore  # noqa: PLC0415

        return SQLiteSessionStore(**kwargs)
    msg = f"Unknown session backend: {backend!r}"
    raise ValueError(msg)


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
