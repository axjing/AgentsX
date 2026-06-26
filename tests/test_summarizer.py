"""Tests for context summarization."""

from __future__ import annotations

from agentsx.context.summarizer import ContextSummarizer
from agentsx.core.types import AgentMessage, MessageRole


class TestContextSummarizer:
    """ContextSummarizer behavior."""

    def test_no_summarize_when_few(self) -> None:
        summarizer = ContextSummarizer(max_recent=10)
        messages = [
            AgentMessage(role=MessageRole.SYSTEM, content="sys"),
            AgentMessage(role=MessageRole.USER, content="hi"),
            AgentMessage(role=MessageRole.ASSISTANT, content="hello"),
        ]
        result = summarizer.summarize(messages)
        assert result.removed_count == 0

    def test_summarize_many_messages(self) -> None:
        summarizer = ContextSummarizer(max_recent=5)
        messages = [
            AgentMessage(role=MessageRole.USER, content=f"msg{i}") for i in range(20)
        ]
        result = summarizer.summarize(messages)
        assert result.removed_count > 0

    def test_inject_summary(self) -> None:
        summarizer = ContextSummarizer(max_recent=2)
        messages = [
            AgentMessage(role=MessageRole.SYSTEM, content="sys"),
            AgentMessage(role=MessageRole.USER, content="a"),
            AgentMessage(role=MessageRole.USER, content="b"),
            AgentMessage(role=MessageRole.USER, content="c"),
        ]
        result = summarizer.inject_summary(messages, "summary here")
        assert len(result) == 4  # system + summary + 2 recent
        assert result[1].content == "summary here"
