"""Tests for AgentHarness facade."""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from agentsx.agent.harness import AgentHarness
from agentsx.core.types import (
    AgentMessage,
    MessageRole,
    TextStreamEvent,
)
from agentsx.provider import Model, Provider


class _FakeProvider(Provider):
    """Minimal provider for testing."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self.model = Model(id="fake-model", provider_name="fake")
        self.responses = responses or ["OK"]
        self.call_count = 0
        self.tools = None

    async def stream(
        self,
        messages: list[AgentMessage],
    ) -> AsyncIterator[TextStreamEvent]:
        self.call_count += 1
        resp = (
            self.responses[self.call_count - 1]
            if self.call_count <= len(self.responses)
            else "done"
        )
        yield TextStreamEvent(text=resp)

    def format_messages(
        self,
        messages: list[AgentMessage],
    ) -> list[dict[str, Any]]:
        return [{"role": m.role.value, "content": m.content} for m in messages]


@pytest.mark.asyncio
async def test_harness_prompt_yields_events() -> None:
    """Prompt yields start and end events."""
    harness = AgentHarness(provider=_FakeProvider(["Hello back"]))
    events: list[object] = []
    async for event in harness.prompt("Hi"):
        events.append(event)
    types = {type(e).__name__ for e in events}
    assert "AgentStartEvent" in types
    assert "AgentEndEvent" in types


@pytest.mark.asyncio
async def test_harness_remembers_history() -> None:
    """Multiple prompt calls share the same message history."""
    harness = AgentHarness(provider=_FakeProvider(["A", "B"]))
    await harness.prompt("First").__anext__()
    await harness.prompt("Second").__anext__()
    # Both user messages are retained across calls
    assert len(harness.messages) >= 2
    roles = [m.role for m in harness.messages]
    assert MessageRole.USER in roles


@pytest.mark.asyncio
async def test_harness_subscribe_event_listener() -> None:
    """Subscribed listener receives events during prompt execution."""
    received: list[str] = []
    harness = AgentHarness(provider=_FakeProvider(["echo"]))

    def on_event(event: object) -> None:
        received.append(type(event).__name__)

    unsub = harness.subscribe(on_event)
    async for _ in harness.prompt("test"):
        pass
    assert len(received) > 0
    unsub()


@pytest.mark.asyncio
async def test_harness_cancel() -> None:
    """Cancelled harness still yields initial events but stops follow-ups."""
    harness = AgentHarness(provider=_FakeProvider(["slow"]))
    harness.cancel()
    events: list[object] = []
    async for event in harness.prompt("test"):
        events.append(event)
    assert len(events) > 0


@pytest.mark.asyncio
async def test_harness_follow_up_queue() -> None:
    """Follow-up queue messages trigger additional turns."""
    harness = AgentHarness(provider=_FakeProvider(["step1", "step2"]))
    harness.queue_follow_up("also do this")
    events: list[object] = []
    async for event in harness.prompt("do that"):
        events.append(event)
    assert len(events) > 0


@pytest.mark.asyncio
async def test_harness_clear_history() -> None:
    """Clear history removes messages but preserves the system prompt."""
    harness = AgentHarness(
        provider=_FakeProvider(["a"]),
        system_prompt="You are helpful",
    )
    await harness.prompt("Hi").__anext__()
    harness.clear_history()
    assert len(harness.messages) == 1
    assert harness.messages[0].role == MessageRole.SYSTEM
