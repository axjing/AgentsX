"""Workspace lifecycle management.

Tracks the active project root, monitors for changes, and provides
project context to the agent loop.

Inspired by codex file-system and hermes project_tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class WorkspaceInfo:
    """Snapshot of the workspace state."""

    root: Path
    has_git: bool
    file_count: int = 0
    dir_count: int = 0
    error: str = ""


class WorkspaceManager:
    """Manages the active workspace directory.

    Usage::

        mgr = WorkspaceManager(root=Path("/workspace"))
        info = mgr.get_info()
        if info.has_git:
            print("Git repo detected")
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root.resolve() if root else Path.cwd()

    @property
    def root(self) -> Path:
        return self._root

    def get_info(self) -> WorkspaceInfo:
        """Gather workspace metadata."""
        if not self._root.is_dir():
            return WorkspaceInfo(
                root=self._root,
                has_git=False,
                error=f"Not a directory: {self._root}",
            )

        has_git = (self._root / ".git").is_dir()
        file_count = 0
        dir_count = 0

        for entry in self._root.rglob("*"):
            if entry.is_file():
                file_count += 1
            elif entry.is_dir():
                dir_count += 1

        return WorkspaceInfo(
            root=self._root,
            has_git=has_git,
            file_count=file_count,
            dir_count=dir_count,
        )

    def set_root(self, root: Path) -> None:
        self._root = root.resolve()

    def is_within(self, path: str | Path) -> bool:
        """Check if *path* is inside the workspace."""
        try:
            Path(path).resolve().relative_to(self._root)
            return True
        except ValueError:
            return False
