"""Conversation trajectory tracking.

Records the full decision chain: thoughts, tool calls, results, and
policy decisions. Enables debugging, replay, and context-aware compaction.

Inspired by hermes-agent trajectory.py and codex message-history.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class TrajectoryEntry:
    """A single step in the agent conversation trajectory."""

    step: int
    action: str  # "think", "tool_call", "tool_result", "error"
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "action": self.action,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrajectoryEntry:
        return cls(
            step=data["step"],
            action=data["action"],
            content=data["content"],
            metadata=data.get("metadata", {}),
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )


class Trajectory:
    """Ordered record of agent decisions and actions.

    Usage::

        traj = Trajectory(session_id="abc123")
        traj.add_think(1, "I should read the file first")
        traj.add_tool_call(1, "tool_file_read", {"path": "main.py"})
        traj.add_tool_result(1, "1: print(hello)", success=True)
    """

    def __init__(self, session_id: str = "") -> None:
        self.session_id = session_id
        self.entries: list[TrajectoryEntry] = []

    def add_think(self, step: int, thought: str) -> None:
        self.entries.append(
            TrajectoryEntry(
                step=step,
                action="think",
                content=thought,
            )
        )

    def add_tool_call(
        self,
        step: int,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> None:
        self.entries.append(
            TrajectoryEntry(
                step=step,
                action="tool_call",
                content=tool_name,
                metadata={"arguments": arguments},
            )
        )

    def add_tool_result(
        self,
        step: int,
        result: str,
        success: bool = True,
        tool_name: str = "",
    ) -> None:
        self.entries.append(
            TrajectoryEntry(
                step=step,
                action="tool_result",
                content=result[:2000],
                metadata={"success": success, "tool_name": tool_name},
            )
        )

    def add_error(self, step: int, error: str) -> None:
        self.entries.append(
            TrajectoryEntry(
                step=step,
                action="error",
                content=error,
            )
        )

    def get_tool_calls(self) -> list[TrajectoryEntry]:
        return [e for e in self.entries if e.action == "tool_call"]

    def get_errors(self) -> list[TrajectoryEntry]:
        return [e for e in self.entries if e.action == "error"]

    def get_steps_with_tools(self) -> set[int]:
        return {
            e.step for e in self.entries if e.action in ("tool_call", "tool_result")
        }

    def summarize(self) -> str:
        """Generate a human-readable summary of the trajectory."""
        if not self.entries:
            return "No actions taken."
        lines = [f"Trajectory ({len(self.entries)} entries):"]
        for entry in self.entries:
            marker = {
                "think": "\U0001f914",
                "tool_call": "\U0001f527",
                "tool_result": "\U0001f4e4",
                "error": "\u274c",
            }.get(entry.action, "?")
            lines.append(f"  {marker} Step {entry.step}: {entry.content[:80]}")
        return "\n".join(lines)

    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(e.to_dict()) for e in self.entries)

    @classmethod
    def from_jsonl(cls, data: str, session_id: str = "") -> Trajectory:
        traj = cls(session_id=session_id)
        for line in data.strip().split("\n"):
            if line.strip():
                traj.entries.append(TrajectoryEntry.from_dict(json.loads(line)))
        return traj
