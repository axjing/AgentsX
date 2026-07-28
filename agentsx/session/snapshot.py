"""Session snapshots — capture and rollback file state.

Provides a safety mechanism for context compaction: before compacting,
capture the state of key files so that if compaction produces bad results,
the session can be rolled back to its pre-compaction state.

Inspired by OpenCode's session revert + snapshot pattern.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FileSnapshot:
    """Captured state of a single file.

    Attributes:
        path: Absolute path to the file.
        content_hash: SHA-256 hash of the file content.
        size: File size in bytes.
        exists: Whether the file existed at capture time.
    """

    path: str
    content_hash: str
    size: int
    exists: bool


@dataclass
class SessionSnapshot:
    """A point-in-time snapshot of file states for a session.

    Usage::

        snapshot = SessionSnapshot("session-123", base_dir=Path("."))
        snapshot.capture([Path("src/main.py"), Path("config.yaml")])
        # ... later, if rollback is needed:
        snapshot.rollback()
    """

    session_id: str
    base_dir: Path
    _file_states: dict[str, FileSnapshot] = field(default_factory=dict)
    _original_contents: dict[str, bytes] = field(default_factory=dict)

    def capture(self, paths: list[Path]) -> None:
        """Capture the current state of the given files.

        Only captures files that exist.  Stores content hashes and
        optionally the full content for rollback.
        """
        for p in paths:
            abs_path = p.resolve()
            path_str = str(abs_path)
            if abs_path.exists():
                try:
                    content = abs_path.read_bytes()
                    content_hash = hashlib.sha256(content).hexdigest()
                    self._file_states[path_str] = FileSnapshot(
                        path=path_str,
                        content_hash=content_hash,
                        size=len(content),
                        exists=True,
                    )
                    self._original_contents[path_str] = content
                except OSError as exc:
                    logger.warning("Failed to capture snapshot for %s: %s", p, exc)
            else:
                self._file_states[path_str] = FileSnapshot(
                    path=path_str,
                    content_hash="",
                    size=0,
                    exists=False,
                )
        logger.debug(
            "Captured snapshot for %d files (session=%s)",
            len(self._file_states),
            self.session_id,
        )

    def rollback(self) -> list[str]:
        """Restore all captured files to their snapshot state.

        Returns:
            List of file paths that were restored.
        """
        restored: list[str] = []
        for path_str, original in self._original_contents.items():
            p = Path(path_str)
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(original)
                restored.append(path_str)
                logger.debug("Rolled back: %s", path_str)
            except OSError as exc:
                logger.error("Failed to rollback %s: %s", path_str, exc)
        logger.info(
            "Rolled back %d files (session=%s)",
            len(restored),
            self.session_id,
        )
        return restored

    def has_changes(self) -> bool:
        """Check if any captured files have changed since snapshot."""
        for path_str, state in self._file_states.items():
            p = Path(path_str)
            if not state.exists and not p.exists():
                continue
            if state.exists != p.exists():
                return True
            if state.exists:
                try:
                    current_hash = hashlib.sha256(p.read_bytes()).hexdigest()
                    if current_hash != state.content_hash:
                        return True
                except OSError:
                    return True
        return False

    @property
    def file_count(self) -> int:
        """Number of files in this snapshot."""
        return len(self._file_states)

    def to_dict(self) -> dict[str, Any]:
        """Serialize snapshot metadata (not file contents) to a dict."""
        return {
            "session_id": self.session_id,
            "base_dir": str(self.base_dir),
            "files": {
                path: {
                    "content_hash": s.content_hash,
                    "size": s.size,
                    "exists": s.exists,
                }
                for path, s in self._file_states.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionSnapshot":
        """Deserialize snapshot metadata from a dict."""
        snap = cls(
            session_id=str(data.get("session_id", "")),
            base_dir=Path(data.get("base_dir", ".")),
        )
        for path, info in data.get("files", {}).items():
            snap._file_states[path] = FileSnapshot(
                path=path,
                content_hash=str(info.get("content_hash", "")),
                size=int(info.get("size", 0)),
                exists=bool(info.get("exists", True)),
            )
        return snap
