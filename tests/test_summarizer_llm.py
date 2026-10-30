"""Tests for ContextSummarizer LLM-driven semantic summarization."""

from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest

from agentsx.context.summarizer import ContextSummarizer
from agentsx.protocol.events import TextStreamEvent
from agentsx.protocol.messages import AgentMessage, MessageRole, ToolCall


class TestContextSummarizerLLM:
    """Tests for ContextSummarizer.summarize_with_provider."""

    @pytest.mark.asyncio
    async def test_summarize_few_messages(self) -> None:
        summarizer = ContextSummarizer(max_recent=5)
        msgs = [
            AgentMessage(role=MessageRole.USER, content=f"msg {i}") for i in range(4)
        ]
        mock_provider = MagicMock()
        res = await summarizer.summarize_with_provider(msgs, mock_provider)
        assert res.summary == ""
        assert res.original_count == 4
        assert res.preserved_count == 4
        assert res.removed_count == 0

    @pytest.mark.asyncio
    async def test_semantic_summary_success(self) -> None:
        summarizer = ContextSummarizer(max_recent=3)
        msgs = [
            AgentMessage(role=MessageRole.SYSTEM, content="System prompt"),
            AgentMessage(role=MessageRole.USER, content="Please build feature X"),
            AgentMessage(
                role=MessageRole.ASSISTANT,
                content="I will inspect files",
                tool_calls=[
                    ToolCall(id="c1", name="tool_file_read", arguments={"path": "a.py"})
                ],
            ),
            AgentMessage(
                role=MessageRole.TOOL,
                content="file content",
                tool_call_id="c1",
            ),
            AgentMessage(role=MessageRole.ASSISTANT, content="I analyzed a.py"),
            AgentMessage(role=MessageRole.USER, content="Now write tests"),
            AgentMessage(role=MessageRole.ASSISTANT, content="Writing tests..."),
            AgentMessage(role=MessageRole.USER, content="Run the suite"),
        ]

        async def fake_stream(
            *args: object, **kwargs: object
        ) -> AsyncIterator[TextStreamEvent]:
            yield TextStreamEvent(text="Goal: Build feature X\n")
            yield TextStreamEvent(text="Progress: Inspected a.py\n")
            yield TextStreamEvent(text="Next Steps: Run test suite")

        mock_provider = MagicMock()
        mock_provider.stream = fake_stream

        res = await summarizer.summarize_with_provider(msgs, mock_provider)
        assert "Goal: Build feature X" in res.summary
        assert res.removed_count > 0

    @pytest.mark.asyncio
    async def test_fallback_on_provider_error(self) -> None:
        summarizer = ContextSummarizer(max_recent=2)
        msgs = [
            AgentMessage(role=MessageRole.USER, content="Query 1"),
            AgentMessage(role=MessageRole.ASSISTANT, content="Answer 1"),
            AgentMessage(role=MessageRole.USER, content="Query 2"),
            AgentMessage(role=MessageRole.ASSISTANT, content="Answer 2"),
            AgentMessage(role=MessageRole.USER, content="Query 3"),
        ]

        async def failing_stream(
            *args: object, **kwargs: object
        ) -> AsyncIterator[TextStreamEvent]:
            raise RuntimeError("API stream error")
            yield TextStreamEvent(text="")

        mock_provider = MagicMock()
        mock_provider.stream = failing_stream

        res = await summarizer.summarize_with_provider(msgs, mock_provider)
        assert "earlier messages summarized" in res.summary
        assert "Assistant spoke" in res.summary
