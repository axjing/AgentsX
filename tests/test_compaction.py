"""Tests for context compaction utility."""

from __future__ import annotations

from agentsx.context.compaction import (
    compact_messages,
    estimate_message_tokens,
    estimate_tokens,
    should_compact,
)
from agentsx.core.types import AgentMessage, MessageRole


class TestEstimateTokens:
    """Token estimation functions."""

    def test_basic_text(self) -> None:
        assert estimate_tokens("hello world") == 2  # 11 chars / 4

    def test_empty_string(self) -> None:
        assert estimate_tokens("") == 0

    def test_message_with_tool_calls(self) -> None:
        from agentsx.core.types import ToolCall

        msg = AgentMessage(
            role=MessageRole.ASSISTANT,
            content="Let me check",
            tool_calls=[
                ToolCall(id="1", name="read", arguments={}),
                ToolCall(id="2", name="grep", arguments={}),
            ],
        )
        # 12 chars = 3 tokens + 2 tool calls * 10 = 23
        assert estimate_message_tokens(msg) == 23


class TestShouldCompact:
    """Compaction trigger logic."""

    def test_few_messages_never_compact(self) -> None:
        msgs = [
            AgentMessage(role=MessageRole.USER, content=f"msg {i}") for i in range(5)
        ]
        assert should_compact(msgs) is False

    def test_compact_on_message_count(self) -> None:
        msgs = [
            AgentMessage(role=MessageRole.USER, content=f"msg {i}") for i in range(60)
        ]
        assert should_compact(msgs, max_messages=50) is True

    def test_no_compact_below_threshold(self) -> None:
        msgs = [
            AgentMessage(role=MessageRole.USER, content=f"msg {i}") for i in range(20)
        ]
        assert should_compact(msgs, max_messages=50) is False


class TestCompactMessages:
    """Message compaction behavior."""

    def test_no_compact_when_few(self) -> None:
        msgs = [
            AgentMessage(role=MessageRole.USER, content=f"msg {i}") for i in range(10)
        ]
        result = compact_messages(msgs)
        assert result is msgs

    def test_compact_preserves_system(self) -> None:
        msgs = [
            AgentMessage(role=MessageRole.SYSTEM, content="You are a bot."),
            *[
                AgentMessage(role=MessageRole.USER, content=f"msg {i}")
                for i in range(30)
            ],
        ]
        result = compact_messages(msgs)
        assert result[0].role == MessageRole.SYSTEM
        assert result[0].content == "You are a bot."

    def test_compact_creates_summary(self) -> None:
        msgs = [
            AgentMessage(role=MessageRole.SYSTEM, content="You are a bot."),
            *[
                AgentMessage(role=MessageRole.USER, content=f"msg {i}")
                for i in range(30)
            ],
        ]
        result = compact_messages(msgs)
        # Second message should be summary
        assert "earlier messages compacted" in result[1].content

    def test_compact_preserves_recent(self) -> None:
        msgs = [
            AgentMessage(role=MessageRole.SYSTEM, content="You are a bot."),
            *[
                AgentMessage(role=MessageRole.USER, content=f"msg {i}")
                for i in range(30)
            ],
        ]
        result = compact_messages(msgs)
        # Last message should be the last one in original
        assert result[-1].content == "msg 29"

    def test_compact_preserves_last_n(self) -> None:
        msgs = [
            AgentMessage(role=MessageRole.SYSTEM, content="You are a bot."),
            *[
                AgentMessage(role=MessageRole.USER, content=f"msg {i}")
                for i in range(30)
            ],
        ]
        result = compact_messages(msgs, preserve_count=5)
        # Should have system + summary + 5 preserved
        assert len(result) == 7  # system + summary + 5
