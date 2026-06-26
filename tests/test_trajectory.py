"""Tests for conversation trajectory tracking."""

from __future__ import annotations

from agentsx.context.trajectory import Trajectory, TrajectoryEntry


class TestTrajectoryEntry:
    """TrajectoryEntry construction and serialization."""

    def test_basic(self) -> None:
        entry = TrajectoryEntry(step=1, action="think", content="hello")
        assert entry.step == 1
        assert entry.action == "think"
        assert entry.content == "hello"

    def test_to_dict(self) -> None:
        entry = TrajectoryEntry(step=1, action="tool_call", content="read")
        d = entry.to_dict()
        assert d["step"] == 1
        assert d["action"] == "tool_call"
        assert d["content"] == "read"

    def test_roundtrip(self) -> None:
        entry = TrajectoryEntry(step=2, action="tool_result", content="ok")
        d = entry.to_dict()
        restored = TrajectoryEntry.from_dict(d)
        assert restored.step == entry.step
        assert restored.action == entry.action


class TestTrajectory:
    """Trajectory management."""

    def test_add_entries(self) -> None:
        traj = Trajectory()
        traj.add_think(1, "thinking")
        traj.add_tool_call(1, "read", {"path": "a.txt"})
        traj.add_tool_result(1, "content", tool_name="read")
        assert len(traj.entries) == 3

    def test_get_tool_calls(self) -> None:
        traj = Trajectory()
        traj.add_think(1, "t")
        traj.add_tool_call(1, "read", {})
        calls = traj.get_tool_calls()
        assert len(calls) == 1
        assert calls[0].content == "read"

    def test_get_steps_with_tools(self) -> None:
        traj = Trajectory()
        traj.add_think(1, "t")
        traj.add_tool_call(2, "read", {})
        traj.add_tool_result(2, "ok", tool_name="read")
        steps = traj.get_steps_with_tools()
        assert steps == {2}

    def test_jsonl_roundtrip(self) -> None:
        traj = Trajectory(session_id="abc")
        traj.add_think(1, "thinking")
        traj.add_tool_call(1, "read", {"path": "x.txt"})
        data = traj.to_jsonl()
        restored = Trajectory.from_jsonl(data, session_id="abc")
        assert len(restored.entries) == 2
        assert restored.entries[0].action == "think"

    def test_summarize_empty(self) -> None:
        traj = Trajectory()
        summary = traj.summarize()
        assert "No actions" in summary

    def test_summarize_with_entries(self) -> None:
        traj = Trajectory()
        traj.add_think(1, "read file")
        traj.add_tool_call(1, "read", {"path": "x.txt"})
        traj.add_tool_result(1, "content", tool_name="read")
        summary = traj.summarize()
        assert "3 entries" in summary
