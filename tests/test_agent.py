"""Tests for agent loop and Agent class."""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from agentsx.agent import Agent, run_agent_loop
from agentsx.core.types import (
    AgentEndEvent,
    AgentEvent,
    AgentMessage,
    AgentStartEvent,
    ErrorEvent,
    MessageRole,
    ModelRequestEvent,
    ModelResponseEvent,
    RetryEvent,
    TextDeltaEvent,
    TextStreamEvent,
    TurnEndEvent,
    TurnStartEvent,
)
from agentsx.provider import Model, Provider
from agentsx.tools import ToolRegistry, tool


class StreamingProvider(Provider):
    """Minimal provider that echoes input with a fixed response."""

    def __init__(self, model: Model, tokens: list[str] | None = None) -> None:
        self.model = model
        self._tokens = tokens if tokens is not None else ["Hello", " world"]

    async def stream(
        self,
        messages: list[AgentMessage],
    ) -> AsyncIterator[TextStreamEvent]:
        for t in self._tokens:
            yield TextStreamEvent(text=t)

    def format_messages(self, messages: list[AgentMessage]) -> list[dict[str, Any]]:
        return [{"role": m.role.value, "content": m.content} for m in messages]


class FailingProvider(Provider):
    """Provider that raises during streaming."""

    def __init__(self, model: Model) -> None:
        self.model = model

    async def stream(
        self,
        messages: list[AgentMessage],
    ) -> AsyncIterator[TextStreamEvent]:
        msg = "API failure"
        raise RuntimeError(msg)
        yield  # noqa: UNR

    def format_messages(self, messages: list[AgentMessage]) -> list[dict[str, Any]]:
        return []


class TestRunAgentLoop:
    """run_agent_loop() basic behaviour."""

    @pytest.mark.asyncio
    async def test_single_response(self) -> None:
        provider = StreamingProvider(model=Model(id="test", provider_name="test"))
        msgs = [AgentMessage(role=MessageRole.USER, content="Hi")]
        events: list[AgentEvent] = []
        async for event in run_agent_loop(provider, msgs):
            events.append(event)

        # AgentStart, TurnStart, ModelRequest, 2x(TextDelta+ModelResponse delta),
        # ModelResponse final, TurnEnd(no tools), AgentEnd = 10 events
        assert len(events) == 10
        assert isinstance(events[0], AgentStartEvent)
        assert isinstance(events[1], TurnStartEvent)
        assert isinstance(events[2], ModelRequestEvent)
        assert events[2].model == "test"
        assert isinstance(events[3], TextDeltaEvent)
        assert isinstance(events[4], ModelResponseEvent)
        assert events[4].delta is True
        assert events[4].content == "Hello"
        assert isinstance(events[5], TextDeltaEvent)
        assert isinstance(events[6], ModelResponseEvent)
        assert events[6].delta is True
        assert events[6].content == " world"
        assert isinstance(events[7], ModelResponseEvent)
        assert events[7].delta is False
        assert events[7].content == "Hello world"
        assert events[7].step == 1
        assert isinstance(events[8], TurnEndEvent)
        assert events[8].had_tool_calls is False
        assert isinstance(events[9], AgentEndEvent)

        assert len(msgs) == 2
        assert msgs[1].role == MessageRole.ASSISTANT
        assert msgs[1].content == "Hello world"

    @pytest.mark.asyncio
    async def test_empty_stream(self) -> None:
        provider = StreamingProvider(
            model=Model(id="test", provider_name="test"),
            tokens=[],
        )
        msgs = [AgentMessage(role=MessageRole.USER, content="Hi")]
        events: list[AgentEvent] = []
        async for event in run_agent_loop(provider, msgs):
            events.append(event)

        # AgentStart, TurnStart, ModelRequest, ModelResponse final, TurnEnd, AgentEnd
        assert len(events) == 6
        assert isinstance(events[0], AgentStartEvent)
        assert isinstance(events[2], ModelRequestEvent)
        assert isinstance(events[3], ModelResponseEvent)
        assert events[3].delta is False
        assert events[3].content == ""

    @pytest.mark.asyncio
    async def test_provider_error(self) -> None:
        provider = FailingProvider(model=Model(id="test", provider_name="test"))
        msgs = [AgentMessage(role=MessageRole.USER, content="Hi")]
        events: list[AgentEvent] = []
        async for event in run_agent_loop(provider, msgs):
            events.append(event)

        # AgentStart, TurnStart, ModelRequest, 3x RetryEvent, ErrorEvent
        assert len(events) == 7
        assert isinstance(events[0], AgentStartEvent)
        assert isinstance(events[2], ModelRequestEvent)
        for i in (3, 4, 5):
            assert isinstance(events[i], RetryEvent)
        assert isinstance(events[6], ErrorEvent)
        assert "retries exhausted" in str(events[6].error)
        assert "FailoverReason.UNKNOWN" in events[6].context


class TestAgent:
    """Agent convenience wrapper."""

    @pytest.mark.asyncio
    async def test_run_with_provider(self) -> None:
        provider = StreamingProvider(model=Model(id="test", provider_name="test"))
        agent = Agent(provider=provider, system_prompt="")
        events: list[AgentEvent] = []
        async for event in agent.run("Hi"):
            events.append(event)

        assert len(events) == 10
        assert isinstance(events[2], ModelRequestEvent)
        assert isinstance(events[-1], AgentEndEvent)
        assert events[-1].reason == "completed"
        # Find the final non-delta ModelResponseEvent
        final_response = [
            e for e in events if isinstance(e, ModelResponseEvent) and not e.delta
        ][0]
        assert final_response.content == "Hello world"

    @pytest.mark.asyncio
    async def test_system_prompt_included(self) -> None:
        provider = StreamingProvider(model=Model(id="test", provider_name="test"))
        agent = Agent(provider=provider, system_prompt="Be helpful.")
        events: list[AgentEvent] = []
        async for event in agent.run("Hi"):
            events.append(event)

        assert any(isinstance(e, ModelRequestEvent) for e in events)

    def test_resolve_provider_with_model_name(self) -> None:
        """Agent can be created with a model name (no provider)."""
        agent = Agent(model_name="gpt-4o")
        assert agent._model_name == "gpt-4o"

    def test_agent_accepts_tools(self) -> None:
        """Agent accepts a ToolRegistry and stores it."""
        registry = ToolRegistry()

        @tool(description="test tool")
        def my_tool() -> str:
            return "ok"

        registry.register(my_tool)
        agent = Agent(
            provider=StreamingProvider(
                model=Model(id="test", provider_name="test"),
            ),
            tools=registry,
        )
        assert agent._tools is registry

    @pytest.mark.asyncio
    async def test_loop_accepts_tools_parameter(self) -> None:
        """run_agent_loop accepts a tools parameter (wired but not yet active)."""
        provider = StreamingProvider(model=Model(id="test", provider_name="test"))
        registry = ToolRegistry()
        msgs = [AgentMessage(role=MessageRole.USER, content="Hi")]
        events: list[AgentEvent] = []
        async for event in run_agent_loop(provider, msgs, tools=registry):
            events.append(event)
        assert len(events) == 10
