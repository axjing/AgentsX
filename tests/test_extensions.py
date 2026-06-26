"""Tests for extension system (``agentsx/extensions.py``)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agentsx.core.types import (
    AgentMessage,
    MessageRole,
    TextStreamEvent,
    ToolCall,
    ToolCallStreamEvent,
)
from agentsx.extensions import (
    ALL_EVENTS,
    EVENT_ON_ERROR,
    EVENT_ON_LOOP_END,
    EVENT_ON_LOOP_START,
    EVENT_ON_MODEL_REQUEST,
    EVENT_ON_MODEL_RESPONSE,
    EVENT_ON_TOOL_CALL,
    EVENT_ON_TOOL_RESULT,
    ExtensionAPI,
    ExtensionEvent,
)


class TestEventConstants:
    """Predefined event types exist and are unique."""

    def test_all_events_defined(self) -> None:
        assert len(ALL_EVENTS) == 7
        assert EVENT_ON_LOOP_START in ALL_EVENTS
        assert EVENT_ON_LOOP_END in ALL_EVENTS
        assert EVENT_ON_MODEL_REQUEST in ALL_EVENTS
        assert EVENT_ON_MODEL_RESPONSE in ALL_EVENTS
        assert EVENT_ON_TOOL_CALL in ALL_EVENTS
        assert EVENT_ON_TOOL_RESULT in ALL_EVENTS
        assert EVENT_ON_ERROR in ALL_EVENTS


class TestExtensionEvent:
    """ExtensionEvent dataclass."""

    def test_basic(self) -> None:
        event = ExtensionEvent(type="on_test", data={"key": "val"})
        assert event.type == "on_test"
        assert event.data == {"key": "val"}

    def test_default_data(self) -> None:
        event = ExtensionEvent(type="on_test")
        assert event.data == {}


class TestExtensionAPI:
    """ExtensionAPI — register, emit, error isolation."""

    @pytest.fixture
    def api(self) -> ExtensionAPI:
        return ExtensionAPI()

    # ── Register & emit ─────────────────────────────────────

    async def test_register_and_emit(self, api: ExtensionAPI) -> None:
        received: list[ExtensionEvent] = []

        async def handler(event: ExtensionEvent) -> None:
            received.append(event)

        api.on(EVENT_ON_TOOL_RESULT, handler)
        event = ExtensionEvent(type=EVENT_ON_TOOL_RESULT, data={"name": "read"})
        await api.emit(event)

        assert len(received) == 1
        assert received[0].type == EVENT_ON_TOOL_RESULT
        assert received[0].data == {"name": "read"}

    async def test_multiple_handlers(self, api: ExtensionAPI) -> None:
        count: list[int] = []

        async def h1(event: ExtensionEvent) -> None:
            count.append(1)

        async def h2(event: ExtensionEvent) -> None:
            count.append(2)

        api.on(EVENT_ON_TOOL_CALL, h1)
        api.on(EVENT_ON_TOOL_CALL, h2)
        await api.emit(ExtensionEvent(type=EVENT_ON_TOOL_CALL))

        assert count == [1, 2]

    async def test_unregistered_event(self, api: ExtensionAPI) -> None:
        """Emitting an event with no handlers is a no-op."""
        await api.emit(ExtensionEvent(type="nonexistent"))  # no error

    async def test_handler_exception_is_caught(self, api: ExtensionAPI) -> None:
        """A handler that raises does not propagate the exception."""

        async def failing(event: ExtensionEvent) -> None:
            raise ValueError("handler error")

        async def good(event: ExtensionEvent) -> None:
            pass  # noqa: B018

        api.on(EVENT_ON_LOOP_START, failing)
        api.on(EVENT_ON_LOOP_START, good)
        # Should not raise
        await api.emit(ExtensionEvent(type=EVENT_ON_LOOP_START))

    # ── load_entry_points ──────────────────────────────────

    def test_load_entry_points_calls_setup(self, api: ExtensionAPI) -> None:
        """load_entry_points discovers and invokes extension setup functions."""
        from unittest.mock import Mock

        called: list[str] = []

        def setup_alpha(api: ExtensionAPI) -> None:
            called.append("alpha")

        mock_entry = Mock()
        mock_entry.name = "alpha"
        mock_entry.load.return_value = setup_alpha

        with patch(
            "agentsx.extensions._entry_points",
            return_value=[mock_entry],
        ):
            api.load_entry_points(group="test.extensions")

        assert called == ["alpha"]

    def test_load_entry_points_skips_bad_setup(self, api: ExtensionAPI) -> None:
        """A broken entry point does not crash load_entry_points."""
        from unittest.mock import Mock

        mock_entry = Mock()
        mock_entry.name = "broken"
        mock_entry.load.side_effect = ImportError("broken module")

        with patch(
            "agentsx.extensions._entry_points",
            return_value=[mock_entry],
        ):
            api.load_entry_points(group="test.extensions")  # no error


# ── Integration with agent loop ──────────────────────────────


class TestExtensionIntegration:
    """Extension events fire correctly during agent loop execution."""

    @pytest.mark.asyncio
    async def test_loop_fires_events(self) -> None:
        """All expected extension events are emitted during a full loop cycle."""
        from unittest.mock import AsyncMock

        from agentsx.agent.loop import run_agent_loop
        from agentsx.provider import Model

        provider = AsyncMock()
        provider.model = Model(id="test", provider_name="test", max_tokens=256)

        from collections.abc import AsyncIterator

        from agentsx.core.types import TextStreamEvent, ToolCallStreamEvent

        async def stream(
            messages: list[AgentMessage],
        ) -> AsyncIterator[TextStreamEvent | ToolCallStreamEvent]:
            yield TextStreamEvent(text="thinking...")
            yield ToolCallStreamEvent(
                tool_call=ToolCall(
                    id="tc1",
                    name="bash",
                    arguments={"command": "echo hi"},
                ),
            )

        provider.stream = stream
        provider.stream_with_retry = stream

        tools = AsyncMock()
        tools.call.return_value = "executed!"

        ext_api = ExtensionAPI()
        fired: list[str] = []

        async def collector(event: ExtensionEvent) -> None:
            fired.append(event.type)

        for evt in ALL_EVENTS:
            ext_api.on(evt, collector)

        messages = [AgentMessage(role=MessageRole.USER, content="do it")]

        async for _ in run_agent_loop(
            provider,
            messages,
            max_steps=1,
            tools=tools,
            extensions=ext_api,
        ):
            pass

        # Should have seen at least LOOP_START, MODEL_REQUEST,
        # MODEL_RESPONSE (final), TOOL_CALL, TOOL_RESULT, LOOP_END
        assert EVENT_ON_LOOP_START in fired
        assert EVENT_ON_MODEL_REQUEST in fired
        assert EVENT_ON_MODEL_RESPONSE in fired
        assert EVENT_ON_TOOL_CALL in fired
        assert EVENT_ON_TOOL_RESULT in fired
        assert EVENT_ON_LOOP_END in fired

    @pytest.mark.asyncio
    async def test_no_extensions_no_crash(self) -> None:
        """Loop works fine when extensions is None."""
        from unittest.mock import AsyncMock

        from agentsx.agent.loop import run_agent_loop
        from agentsx.provider import Model

        provider = AsyncMock()
        provider.model = Model(id="test", provider_name="test", max_tokens=256)
        provider.stream.return_value = AsyncMock()
        provider.stream.return_value.__aiter__.return_value = iter([])

        async def empty_stream(messages):
            return
            yield

        provider.stream = empty_stream
        provider.stream_with_retry = empty_stream

        messages = [AgentMessage(role=MessageRole.USER, content="hello")]

        async for _ in run_agent_loop(provider, messages, max_steps=1):
            pass  # no crash

    @pytest.mark.asyncio
    async def test_error_event_on_stream_failure(self) -> None:
        """An error during streaming fires EVENT_ON_ERROR."""
        from unittest.mock import AsyncMock

        from agentsx.agent.loop import run_agent_loop
        from agentsx.provider import Model

        provider = AsyncMock()
        provider.model = Model(id="test", provider_name="test", max_tokens=256)

        from collections.abc import AsyncIterator

        async def stream(
            messages: list[AgentMessage],
        ) -> AsyncIterator[ToolCallStreamEvent]:
            raise RuntimeError("stream crashed")

        provider.stream = stream
        provider.stream_with_retry = stream

        ext_api = ExtensionAPI()
        fired: list[str] = []

        async def collector(event: ExtensionEvent) -> None:
            fired.append(event.type)

        ext_api.on(EVENT_ON_ERROR, collector)

        messages = [AgentMessage(role=MessageRole.USER, content="hi")]

        async for _ in run_agent_loop(
            provider,
            messages,
            max_steps=1,
            extensions=ext_api,
        ):
            pass

        assert EVENT_ON_ERROR in fired
