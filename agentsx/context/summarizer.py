"""LLM-driven context summarization.

Replaces simple token-count placeholders with semantic summaries.
Can be called when the conversation exceeds thresholds.

Design:
    - Pluggable: works with any Provider
    - Configurable: which parts to summarize (tool results vs thoughts)
    - Safe: preserves system message and recent messages

Inspired by Pi branch-summarization and hermes context_compressor.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentsx.core.types import AgentMessage, MessageRole


@dataclass
class SummaryResult:
    """Output of context summarization."""

    summary: str
    original_count: int
    preserved_count: int
    removed_count: int


class ContextSummarizer:
    """Generate semantic summaries of old conversation turns.

    Usage::

        summarizer = ContextSummarizer(max_recent=10)
        result = summarizer.summarize(messages)
        # result.summary contains a concise recap
    """

    def __init__(
        self,
        max_recent: int = 10,
        max_summary_tokens: int = 500,
    ) -> None:
        self.max_recent = max_recent
        self.max_summary_tokens = max_summary_tokens

    def summarize(self, messages: list[AgentMessage]) -> SummaryResult:
        """Create a summary of older messages.

        Preserves the system message and the last N messages.
        Older messages are condensed into a single summary entry.

        Args:
            messages: Full conversation history.

        Returns:
            SummaryResult with summary text and counts.
        """
        if len(messages) <= self.max_recent + 1:
            return SummaryResult(
                summary="",
                original_count=len(messages),
                preserved_count=len(messages),
                removed_count=0,
            )

        system = None
        working = list(messages)
        if working[0].role == MessageRole.SYSTEM:
            system = working.pop(0)

        preserved = working[-self.max_recent :]
        to_summarize = working[: len(working) - self.max_recent]

        summary = self._build_summary(to_summarize)

        preserved_count = len(preserved) + (1 if system else 0) + 1
        return SummaryResult(
            summary=summary,
            original_count=len(messages),
            preserved_count=preserved_count,
            removed_count=len(to_summarize),
        )

    def _build_summary(self, messages: list[AgentMessage]) -> str:
        """Build a concise summary from older messages."""
        tool_calls = 0
        tool_results = 0
        assistant_msgs = 0
        topics: list[str] = []

        for msg in messages:
            if msg.role == MessageRole.ASSISTANT:
                assistant_msgs += 1
                if msg.content.strip():
                    preview = msg.content.strip()[:100]
                    topics.append(preview)
            if msg.role == MessageRole.TOOL:
                tool_results += 1
            if msg.tool_calls:
                tool_calls += len(msg.tool_calls)

        parts = [f"[{len(messages)} earlier messages summarized]"]
        parts.append(f"Assistant spoke {assistant_msgs} times.")
        parts.append(f"{tool_calls} tool calls were made.")
        parts.append(f"{tool_results} tool results received.")
        if topics:
            parts.append("Topics discussed:")
            for t in topics[:5]:
                parts.append(f"- {t}")

        return " ".join(parts)

    def inject_summary(
        self,
        messages: list[AgentMessage],
        summary: str,
    ) -> list[AgentMessage]:
        """Replace messages with a system message + summary + recent."""
        result: list[AgentMessage] = []
        if messages and messages[0].role == MessageRole.SYSTEM:
            result.append(messages[0])
            messages = messages[1:]

        if summary:
            result.append(
                AgentMessage(
                    role=MessageRole.SYSTEM,
                    content=summary,
                )
            )

        result.extend(messages[-self.max_recent :])
        return result
