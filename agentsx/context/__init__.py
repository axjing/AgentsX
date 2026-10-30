"""Context management for long conversations.

Provides token-count based compaction, trajectory tracking,
LLM-driven summarization, and task planning.
"""

from agentsx.context.compaction import (
    compact_messages,
    compact_messages_with_pruning,
    estimate_message_tokens,
    estimate_tokens,
    should_compact,
)
from agentsx.context.manager import ContextManager
from agentsx.context.plan import TaskItem, TaskPlan, TaskStatus, get_active_plan
from agentsx.context.summarizer import ContextSummarizer, SummaryResult
from agentsx.context.tool_pruner import (
    prune_messages_for_compaction,
    summarize_tool_call,
)
from agentsx.context.trajectory import Trajectory, TrajectoryEntry

__all__ = [
    "compact_messages",
    "compact_messages_with_pruning",
    "estimate_message_tokens",
    "estimate_tokens",
    "should_compact",
    "ContextManager",
    "ContextSummarizer",
    "SummaryResult",
    "TaskItem",
    "TaskPlan",
    "TaskStatus",
    "Trajectory",
    "TrajectoryEntry",
    "get_active_plan",
    "prune_messages_for_compaction",
    "summarize_tool_call",
]
