"""Unified context management interface.

Coordinates compaction, summarization, and trajectory tracking
into a single ContextManager.

Usage::

    manager = ContextManager(max_messages=50)
    manager.track_thought(1, "Thinking...")
    if manager.should_compact(messages):
        compacted = manager.compact(messages)
"""

from __future__ import annotations

from agentsx.context.compaction import compact_messages, should_compact
from agentsx.context.summarizer import ContextSummarizer, SummaryResult
from agentsx.context.trajectory import Trajectory
from agentsx.core.types import AgentMessage


class ContextManager:
    """Manages conversation context: compaction, summarization, tracking."""

    def __init__(
        self,
        max_messages: int = 50,
        max_tokens: int = 0,
        max_recent: int = 10,
        session_id: str = "",
    ) -> None:
        self._max_messages = max_messages
        self._max_tokens = max_tokens
        self._summarizer = ContextSummarizer(max_recent=max_recent)
        self.trajectory = Trajectory(session_id=session_id)

    @property
    def trajectory(self) -> Trajectory:
        return self._trajectory

    @trajectory.setter
    def trajectory(self, value: Trajectory) -> None:
        self._trajectory = value

    def should_compact(self, messages: list[AgentMessage]) -> bool:
        return should_compact(
            messages,
            max_tokens=self._max_tokens,
            max_messages=self._max_messages,
        )

    def compact(self, messages: list[AgentMessage]) -> list[AgentMessage]:
        """Compact messages with summarization."""
        summary_result = self._summarizer.summarize(messages)
        if summary_result.removed_count > 0:
            compacted = compact_messages(messages)
            return self._summarizer.inject_summary(
                compacted,
                summary_result.summary,
            )
        return messages

    def summarize(self, messages: list[AgentMessage]) -> SummaryResult:
        return self._summarizer.summarize(messages)
