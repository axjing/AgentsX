"""Tests for workspace awareness modules."""

from __future__ import annotations

import tempfile
from pathlib import Path

from agentsx.workspace.file_tree import FileTreeIndex
from agentsx.workspace.manager import WorkspaceManager


class TestWorkspaceManager:
    """WorkspaceManager behavior."""

    def test_default_root(self) -> None:
        mgr = WorkspaceManager()
        assert mgr.root == Path.cwd()

    def test_custom_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = WorkspaceManager(root=Path(tmpdir))
            assert mgr.root == Path(tmpdir)

    def test_is_within(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = WorkspaceManager(root=Path(tmpdir))
            assert mgr.is_within(Path(tmpdir) / "src")
            assert not mgr.is_within("/etc/passwd")

    def test_get_info(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.txt").write_text("hello")
            (Path(tmpdir) / "sub").mkdir()
            mgr = WorkspaceManager(root=Path(tmpdir))
            info = mgr.get_info()
            assert info.file_count >= 1
            assert info.dir_count >= 1


class TestFileTreeIndex:
    """FileTreeIndex behavior."""

    def test_build_simple(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.txt").write_text("hello")
            (Path(tmpdir) / "b.py").write_text("print(1)")
            idx = FileTreeIndex(root=Path(tmpdir))
            tree = idx.build()
            assert tree.is_dir
            assert len(tree.children) == 2

    def test_as_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.txt").write_text("x")
            idx = FileTreeIndex(root=Path(tmpdir))
            text = idx.as_text()
            assert "a.txt" in text

    def test_find_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.py").write_text("x")
            (Path(tmpdir) / "b.py").write_text("y")
            (Path(tmpdir) / "c.txt").write_text("z")
            idx = FileTreeIndex(root=Path(tmpdir))
            py_files = idx.find_files("*.py")
            assert len(py_files) == 2
