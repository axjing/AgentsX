"""Tests for expanded agent event types."""

from datetime import datetime

from agentsx.protocol.events import (
    AgentEndEvent,
    AgentEvent,
    AgentStartEvent,
    RetryEvent,
    TextDeltaEvent,
    ToolExecutionStartEvent,
    TurnEndEvent,
    TurnStartEvent,
)


def test_agent_start_event() -> None:
    """AgentStartEvent carries model name and step number."""
    event = AgentStartEvent(model="gpt-4o", step=1)
    assert event.model == "gpt-4o"
    assert event.step == 1
    assert isinstance(event.timestamp, datetime)


def test_agent_end_event() -> None:
    """AgentEndEvent carries step, reason, and timestamp."""
    event = AgentEndEvent(step=3, reason="completed")
    assert event.step == 3
    assert event.reason == "completed"
    assert isinstance(event.timestamp, datetime)


def test_turn_start_event() -> None:
    """TurnStartEvent carries turn number."""
    event = TurnStartEvent(turn=2)
    assert event.turn == 2
    assert isinstance(event.timestamp, datetime)


def test_turn_end_event_no_tools() -> None:
    """TurnEndEvent tracks whether tools were invoked."""
    event = TurnEndEvent(turn=1, had_tool_calls=False)
    assert event.had_tool_calls is False
    assert isinstance(event.timestamp, datetime)


def test_text_delta_event() -> None:
    """TextDeltaEvent carries a single text token."""
    event = TextDeltaEvent(text="Hello")
    assert event.text == "Hello"
    assert isinstance(event.timestamp, datetime)


def test_retry_event() -> None:
    """RetryEvent carries attempt details and delay."""
    event = RetryEvent(
        attempt=2,
        max_attempts=3,
        reason="rate limit",
        delay=5.0,
    )
    assert event.attempt == 2
    assert event.max_attempts == 3
    assert event.reason == "rate limit"
    assert event.delay == 5.0
    assert isinstance(event.timestamp, datetime)


def test_tool_execution_start_event() -> None:
    """ToolExecutionStartEvent carries tool name and call ID."""
    event = ToolExecutionStartEvent(tool_name="file_read", tool_call_id="tc_001")
    assert event.tool_name == "file_read"
    assert event.tool_call_id == "tc_001"
    assert isinstance(event.timestamp, datetime)


def test_agent_event_union_dispatch() -> None:
    """All new event types are members of the AgentEvent union."""
    events: list[AgentEvent] = [
        AgentStartEvent(model="gpt-4o", step=1),
        AgentEndEvent(step=1, reason="completed"),
        TurnStartEvent(turn=1),
        TurnEndEvent(turn=1, had_tool_calls=True),
        TextDeltaEvent(text="hi"),
        RetryEvent(attempt=1, max_attempts=3, reason="timeout", delay=5.0),
        ToolExecutionStartEvent(tool_name="bash", tool_call_id="x"),
    ]
    for event in events:
        assert isinstance(event, AgentEvent)
