"""Tests for session snapshots (``agentsx/session/snapshot.py``)."""

from pathlib import Path

import pytest

from agentsx.session.snapshot import FileSnapshot, SessionSnapshot


class TestFileSnapshot:
    """FileSnapshot dataclass."""

    def test_creation(self) -> None:
        snap = FileSnapshot(
            path="/tmp/test.py",
            content_hash="abc123",
            size=1024,
            exists=True,
        )
        assert snap.path == "/tmp/test.py"
        assert snap.content_hash == "abc123"
        assert snap.size == 1024
        assert snap.exists is True


class TestSessionSnapshot:
    """SessionSnapshot — capture, rollback, change detection."""

    def test_capture_existing_files(self, tmp_path: Path) -> None:
        # Create test files
        file_a = tmp_path / "a.py"
        file_b = tmp_path / "b.py"
        file_a.write_text("print('hello')")
        file_b.write_text("print('world')")

        snap = SessionSnapshot(session_id="test-1", base_dir=tmp_path)
        snap.capture([file_a, file_b])

        assert snap.file_count == 2

    def test_capture_nonexistent_file(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.py"
        snap = SessionSnapshot(session_id="test-1", base_dir=tmp_path)
        snap.capture([missing])

        assert snap.file_count == 1
        assert not snap._file_states[str(missing.resolve())].exists

    def test_rollback(self, tmp_path: Path) -> None:
        file_a = tmp_path / "a.py"
        file_a.write_text("original content")

        snap = SessionSnapshot(session_id="test-1", base_dir=tmp_path)
        snap.capture([file_a])

        # Modify file
        file_a.write_text("modified content")
        assert file_a.read_text() == "modified content"

        # Rollback
        restored = snap.rollback()
        assert len(restored) == 1
        assert file_a.read_text() == "original content"

    def test_has_changes_false(self, tmp_path: Path) -> None:
        file_a = tmp_path / "a.py"
        file_a.write_text("content")

        snap = SessionSnapshot(session_id="test-1", base_dir=tmp_path)
        snap.capture([file_a])

        assert not snap.has_changes()

    def test_has_changes_true(self, tmp_path: Path) -> None:
        file_a = tmp_path / "a.py"
        file_a.write_text("content")

        snap = SessionSnapshot(session_id="test-1", base_dir=tmp_path)
        snap.capture([file_a])

        file_a.write_text("modified")
        assert snap.has_changes()

    def test_has_changes_new_file(self, tmp_path: Path) -> None:
        file_a = tmp_path / "a.py"
        file_a.write_text("content")

        snap = SessionSnapshot(session_id="test-1", base_dir=tmp_path)
        snap.capture([file_a])

        file_b = tmp_path / "b.py"
        file_b.write_text("new")
        # New file not in snapshot, so no changes detected
        assert not snap.has_changes()

    def test_rollback_nonexistent_file_noop(self, tmp_path: Path) -> None:
        # Capture a file that doesn't exist
        file_a = tmp_path / "a.py"
        snap = SessionSnapshot(session_id="test-1", base_dir=tmp_path)
        snap.capture([file_a])

        # File still doesn't exist — rollback is a no-op
        restored = snap.rollback()
        assert len(restored) == 0
        assert not file_a.exists()

    def test_to_dict_roundtrip(self, tmp_path: Path) -> None:
        file_a = tmp_path / "a.py"
        file_a.write_text("content")

        snap = SessionSnapshot(session_id="test-1", base_dir=tmp_path)
        snap.capture([file_a])

        data = snap.to_dict()
        restored = SessionSnapshot.from_dict(data)

        assert restored.session_id == "test-1"
        assert restored.file_count == 1

    def test_capture_multiple_files(self, tmp_path: Path) -> None:
        files = []
        for i in range(5):
            f = tmp_path / f"file_{i}.py"
            f.write_text(f"content {i}")
            files.append(f)

        snap = SessionSnapshot(session_id="test-1", base_dir=tmp_path)
        snap.capture(files)

        assert snap.file_count == 5

        # Modify all files
        for f in files:
            f.write_text("modified")

        assert snap.has_changes()

        # Rollback all
        restored = snap.rollback()
        assert len(restored) == 5

        for i, f in enumerate(files):
            assert f.read_text() == f"content {i}"
