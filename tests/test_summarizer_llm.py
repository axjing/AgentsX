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

    @pytest.mark.asyncio
    async def test_fallback_on_timeout(self) -> None:
        summarizer = ContextSummarizer(max_recent=2)
        msgs = [
            AgentMessage(role=MessageRole.USER, content="Query 1"),
            AgentMessage(role=MessageRole.ASSISTANT, content="Answer 1"),
            AgentMessage(role=MessageRole.USER, content="Query 2"),
            AgentMessage(role=MessageRole.ASSISTANT, content="Answer 2"),
            AgentMessage(role=MessageRole.USER, content="Query 3"),
        ]

        async def slow_stream(
            *args: object, **kwargs: object
        ) -> AsyncIterator[TextStreamEvent]:
            import asyncio

            await asyncio.sleep(0.5)
            yield TextStreamEvent(text="Slow response")

        mock_provider = MagicMock()
        mock_provider.stream = slow_stream

        res = await summarizer.summarize_with_provider(
            msgs, mock_provider, timeout=0.05
        )
        assert "earlier messages summarized" in res.summary


class TestContextManagerLLM:
    """Tests for ContextManager LLM summarization methods."""

    @pytest.mark.asyncio
    async def test_context_manager_compact_with_provider(self) -> None:
        from agentsx.context.manager import ContextManager

        cm = ContextManager(max_messages=10, max_recent=3)
        msgs = [
            AgentMessage(role=MessageRole.SYSTEM, content="System prompt"),
            *[
                AgentMessage(role=MessageRole.USER, content=f"Step {i}")
                for i in range(12)
            ],
        ]

        async def fake_stream(
            *args: object, **kwargs: object
        ) -> AsyncIterator[TextStreamEvent]:
            yield TextStreamEvent(text="Summary: Executed 12 steps successfully.")

        mock_provider = MagicMock()
        mock_provider.stream = fake_stream

        compacted = await cm.compact_with_provider(msgs, mock_provider)
        assert len(compacted) < len(msgs)
        assert compacted[0].content == "System prompt"
        assert "Summary: Executed 12 steps" in compacted[1].content
        assert compacted[-1].content == "Step 11"


class TestAgentLoopSemanticCompaction:
    """Tests for agent loop _compact_context with LLM provider."""

    @pytest.mark.asyncio
    async def test_loop_compact_context_with_provider(self) -> None:
        from agentsx.agent.loop import _compact_context

        msgs = [
            AgentMessage(role=MessageRole.SYSTEM, content="System prompt"),
            *[
                AgentMessage(role=MessageRole.USER, content=f"User request {i}")
                for i in range(25)
            ],
        ]

        async def fake_stream(
            *args: object, **kwargs: object
        ) -> AsyncIterator[TextStreamEvent]:
            yield TextStreamEvent(
                text="Goal: Process requests\nProgress: 25 requests\nNext: Continue"
            )

        mock_provider = MagicMock()
        mock_provider.stream = fake_stream

        events = [
            ev
            async for ev in _compact_context(
                msgs,
                compact=True,
                compact_max_tokens=0,
                compact_max_messages=15,
                provider=mock_provider,
            )
        ]

        assert len(events) == 1
        assert events[0].compacted_count > 0
        assert len(msgs) < 26
        # Second message has semantic summary + end marker
        assert "Goal: Process requests" in msgs[1].content
        assert "END OF CONTEXT SUMMARY" in msgs[1].content

    @pytest.mark.asyncio
    async def test_loop_compact_context_fallback_on_error(self) -> None:
        from agentsx.agent.loop import _compact_context

        msgs = [
            AgentMessage(role=MessageRole.SYSTEM, content="System prompt"),
            *[
                AgentMessage(role=MessageRole.USER, content=f"Request {i}")
                for i in range(25)
            ],
        ]

        async def failing_stream(
            *args: object, **kwargs: object
        ) -> AsyncIterator[TextStreamEvent]:
            raise RuntimeError("API connection failure")
            yield TextStreamEvent(text="")

        mock_provider = MagicMock()
        mock_provider.stream = failing_stream

        events = [
            ev
            async for ev in _compact_context(
                msgs,
                compact=True,
                compact_max_tokens=0,
                compact_max_messages=15,
                provider=mock_provider,
            )
        ]

        assert len(events) == 1
        assert events[0].compacted_count > 0
        assert len(msgs) < 26
        # Fallback structured compaction executed
        assert "earlier messages compacted" in msgs[1].content
