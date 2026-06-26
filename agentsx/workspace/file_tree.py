"""File tree index for workspace context.

Builds a lightweight index of the workspace file structure,
used for path completion and contextual awareness.

Inspired by codex file-search and hermes file state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileTreeNode:
    """A single entry in the file tree."""

    name: str
    is_dir: bool
    path: str
    children: list[FileTreeNode] = field(default_factory=list)


# Default ignored patterns
_DEFAULT_IGNORE: set[str] = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
}


class FileTreeIndex:
    """Lightweight index of workspace file structure."""

    def __init__(
        self,
        root: Path | None = None,
        max_depth: int = 3,
        ignored: set[str] | None = None,
    ) -> None:
        self._root = root or Path.cwd()
        self._max_depth = max_depth
        self._ignored = ignored or _DEFAULT_IGNORE
        self._tree: FileTreeNode | None = None

    def build(self) -> FileTreeNode:
        """Build the file tree index."""
        self._tree = self._build_node(self._root, depth=0)
        return self._tree

    def _build_node(self, path: Path, depth: int) -> FileTreeNode:
        node = FileTreeNode(name=path.name, is_dir=path.is_dir(), path=str(path))
        if path.is_dir() and depth < self._max_depth:
            for entry in sorted(path.iterdir()):
                if entry.name in self._ignored:
                    continue
                try:
                    child = self._build_node(entry, depth + 1)
                    node.children.append(child)
                except PermissionError:
                    continue
        return node

    def as_text(self, indent: str = "  ") -> str:
        """Render the file tree as indented text."""
        if self._tree is None:
            self.build()
        lines: list[str] = []
        self._render(self._tree, lines, indent, level=0)
        return "\n".join(lines)

    def _render(
        self,
        node: FileTreeNode | None,
        lines: list[str],
        indent: str,
        level: int,
    ) -> None:
        if node is None:
            return
        prefix = indent * level
        marker = "/" if node.is_dir else ""
        lines.append(f"{prefix}{node.name}{marker}")
        for child in node.children:
            self._render(child, lines, indent, level + 1)

    def find_files(self, pattern: str) -> list[str]:
        """Find files matching a glob pattern."""
        return [str(p) for p in self._root.rglob(pattern) if p.is_file()]
