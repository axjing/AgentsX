"""Tests for workspace awareness modules."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from agentsx.workspace.file_tree import FileTreeIndex
from agentsx.workspace.git import GitWatcher
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


class TestGitWatcher:
    """GitWatcher behavior."""

    def test_not_a_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            watcher = GitWatcher(root=Path(tmpdir))
            status = watcher.get_status()
            assert status.error == "Not a git repository"
            assert not status.is_dirty

    def test_git_status_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            (repo_path / ".git").mkdir()
            watcher = GitWatcher(root=repo_path)

            def mock_run_git(*args: str) -> str:
                if args[0] == "rev-parse":
                    return "main\n"
                return ""

            with patch.object(watcher, "_run_git", side_effect=mock_run_git):
                status = watcher.get_status()
                assert status.branch == "main"
                assert status.modified_files == []
                assert status.untracked_count == 0
                assert not status.is_dirty
                assert not status.error

    def test_git_status_staged_and_unstaged_dedup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            (repo_path / ".git").mkdir()
            watcher = GitWatcher(root=repo_path)

            def mock_run_git(*args: str) -> str:
                if args[0] == "rev-parse":
                    return "feature/test\n"
                if args[0] == "diff" and len(args) == 2:
                    return "file1.py\nfile2.py\n"
                if args[0] == "diff" and "--cached" in args:
                    return "file2.py\nfile3.py\n"
                if args[0] == "ls-files":
                    return "untracked1.txt\nuntracked2.txt\n"
                return ""

            with patch.object(watcher, "_run_git", side_effect=mock_run_git):
                status = watcher.get_status()
                assert status.branch == "feature/test"
                assert status.modified_files == ["file1.py", "file2.py", "file3.py"]
                assert status.untracked_count == 2
                assert status.is_dirty

    def test_git_status_timeout_or_os_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            (repo_path / ".git").mkdir()
            watcher = GitWatcher(root=repo_path)

            with patch.object(
                watcher, "_run_git", side_effect=OSError("git not found")
            ):
                status = watcher.get_status()
                assert "git not found" in status.error
                assert not status.is_dirty
