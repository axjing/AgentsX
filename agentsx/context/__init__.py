"""Context management for long conversations.

Provides token-count based compaction, trajectory tracking,
and LLM-driven summarization.
"""

from __future__ import annotations

from agentsx.context.compaction import (
    compact_messages,
    estimate_message_tokens,
    estimate_tokens,
    should_compact,
)
from agentsx.context.manager import ContextManager
from agentsx.context.summarizer import ContextSummarizer, SummaryResult
from agentsx.context.trajectory import Trajectory, TrajectoryEntry

__all__ = [
    "compact_messages",
    "estimate_message_tokens",
    "estimate_tokens",
    "should_compact",
    "ContextManager",
    "ContextSummarizer",
    "SummaryResult",
    "Trajectory",
    "TrajectoryEntry",
]
