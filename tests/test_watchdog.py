"""Tests for Watchdog anomaly detection and loop break intervention."""

from collections.abc import AsyncIterator

import pytest

from agentsx.agent.loop import run_agent_loop
from agentsx.agent.watchdog import Watchdog
from agentsx.protocol.events import (
    StreamEvent,
    TextStreamEvent,
    ToolCallStreamEvent,
    WatchdogEvent,
)
from agentsx.protocol.messages import AgentMessage, MessageRole, ToolCall
from agentsx.provider import Model, Provider
from agentsx.tools import ToolRegistry, ToolSpec


class TestWatchdogUnit:
    """Unit tests for the Watchdog class."""

    def test_normal_different_calls(self) -> None:
        wd = Watchdog(max_identical_calls=3, max_consecutive_errors=4)
        w1 = wd.record_tool_call("tool_file_read", {"path": "a.py"}, is_error=False)
        w2 = wd.record_tool_call("tool_file_read", {"path": "b.py"}, is_error=False)
        w3 = wd.record_tool_call("tool_file_glob", {"pattern": "*.py"}, is_error=False)
        assert w1 is None
        assert w2 is None
        assert w3 is None

    def test_identical_call_thrashing(self) -> None:
        wd = Watchdog(max_identical_calls=3, max_consecutive_errors=4)
        w1 = wd.record_tool_call("tool_file_read", {"path": "a.py"}, is_error=False)
        w2 = wd.record_tool_call("tool_file_read", {"path": "a.py"}, is_error=False)
        w3 = wd.record_tool_call("tool_file_read", {"path": "a.py"}, is_error=False)
        assert w1 is None
        assert w2 is None
        assert w3 is not None
        assert w3.kind == "thrashing"
        assert w3.tool_name == "tool_file_read"
        assert w3.count == 3
        assert "called 3 times consecutively" in w3.message

    def test_consecutive_errors(self) -> None:
        wd = Watchdog(max_identical_calls=3, max_consecutive_errors=3)
        w1 = wd.record_tool_call("tool_bash", {"command": "cmd1"}, is_error=True)
        w2 = wd.record_tool_call("tool_bash", {"command": "cmd2"}, is_error=True)
        w3 = wd.record_tool_call("tool_bash", {"command": "cmd3"}, is_error=True)
        assert w1 is None
        assert w2 is None
        assert w3 is not None
        assert w3.kind == "consecutive_errors"
        assert w3.count == 3
        assert "3 consecutive tool execution errors" in w3.message

    def test_error_recovery_resets_error_count(self) -> None:
        wd = Watchdog(max_identical_calls=3, max_consecutive_errors=3)
        assert wd.record_tool_call("tool_bash", {"cmd": "c1"}, is_error=True) is None
        assert wd.record_tool_call("tool_bash", {"cmd": "c2"}, is_error=True) is None
        # Success interrupts consecutive errors
        assert wd.record_tool_call("tool_bash", {"cmd": "c3"}, is_error=False) is None
        assert wd.record_tool_call("tool_bash", {"cmd": "c4"}, is_error=True) is None

    def test_reset(self) -> None:
        wd = Watchdog(max_identical_calls=2)
        wd.record_tool_call("t", {"a": 1})
        wd.reset()
        assert wd.record_tool_call("t", {"a": 1}) is None


class TestWatchdogIntegration:
    """Integration test of Watchdog in run_agent_loop."""

    @pytest.mark.asyncio
    async def test_watchdog_emits_event_and_injects_message(self) -> None:
        # Mock provider issues the same tool call 3 times, then stops
        call_count = 0

        class _LoopingProvider(Provider):
            def __init__(self) -> None:
                self.model = Model(
                    id="mock-model",
                    provider_name="mock",
                    max_tokens=4096,
                )
                self.tools = None

            async def stream(
                self,
                messages: list[AgentMessage],
            ) -> AsyncIterator[StreamEvent]:
                nonlocal call_count
                call_count += 1
                if call_count <= 3:
                    yield ToolCallStreamEvent(
                        tool_call=ToolCall(
                            id=f"call_{call_count}",
                            name="dummy_tool",
                            arguments={"param": "value"},
                        )
                    )
                else:
                    yield TextStreamEvent(text="Finished after warning")

            def format_messages(
                self,
                messages: list[AgentMessage],
            ) -> list[dict[str, object]]:
                return []

        registry = ToolRegistry()
        registry.register(
            ToolSpec(name="dummy_tool", description="", fn=lambda param: "ok")
        )

        messages = [AgentMessage(role=MessageRole.USER, content="Start")]
        provider = _LoopingProvider()

        events = []
        async for event in run_agent_loop(
            provider=provider,
            messages=messages,
            max_steps=5,
            tools=registry,
        ):
            events.append(event)

        watchdog_events = [e for e in events if isinstance(e, WatchdogEvent)]
        assert len(watchdog_events) == 1
        assert watchdog_events[0].tool_name == "dummy_tool"
        assert watchdog_events[0].count == 3

        # Check injected message
        alert_msgs = [m for m in messages if "[System Watchdog Alert:" in m.content]
        assert len(alert_msgs) == 1
