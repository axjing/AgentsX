"""Tests for path security guard."""

from __future__ import annotations

import tempfile
from pathlib import Path

from agentsx.security.path_guard import PathGuard, _has_traversal_pattern


class TestHasTraversalPattern:
    """Traversal pattern detection."""

    def test_detects_double_dot(self) -> None:
        assert _has_traversal_pattern("../etc/passwd")

    def test_detects_nested(self) -> None:
        assert _has_traversal_pattern("../../../secret")

    def test_clean_path(self) -> None:
        assert not _has_traversal_pattern("src/utils/helpers.py")

    def test_backslash_traversal(self) -> None:
        assert _has_traversal_pattern("..\\..\\etc\\passwd")


class TestPathGuard:
    """PathGuard workspace confinement."""

    def test_safe_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "src").mkdir()
            guard = PathGuard(workspace=workspace)
            guard.check("src/main.py")
            # Relative paths resolve against cwd, so we use absolute path
            result2 = guard.check(workspace / "src" / "main.py")
            assert result2.is_safe

    def test_workspace_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            guard = PathGuard(workspace=workspace)
            result = guard.check("/etc/passwd")
            assert not result.is_safe
            assert "escapes workspace" in result.reason

    def test_no_workspace(self) -> None:
        guard = PathGuard(workspace=None)
        result = guard.check("/tmp/test.txt")
        assert result.is_safe  # no workspace = no restriction

    def test_symlink_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "target.txt"
            target.write_text("data")
            link = workspace / "link"
            link.symlink_to(target)
            guard = PathGuard(workspace=workspace, allow_symlinks=False)
            result = guard.check(str(link))
            assert not result.is_safe
            assert "Symlink" in result.reason

    def test_symlink_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            target = workspace / "target.txt"
            target.write_text("data")
            link = workspace / "link"
            link.symlink_to(target)
            guard = PathGuard(workspace=workspace, allow_symlinks=True)
            result = guard.check(str(link))
            assert result.is_safe

    def test_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            guard = PathGuard(workspace=workspace)
            assert guard.is_allowed(workspace / "src" / "main.py")
            assert not guard.is_allowed("/etc/passwd")
