"""Tests for the provider transport abstraction layer."""

import json
from collections.abc import AsyncIterator

from agentsx.core.types import (
    AgentMessage,
    MessageRole,
    TextStreamEvent,
    ToolCall,
    ToolCallStreamEvent,
)
from agentsx.provider.transport import AnthropicTransport, OpenAITransport


class _MockSSELines:
    """Mock response whose aiter_lines yields the given string lines."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line


def test_openai_transport_format_messages() -> None:
    transport = OpenAITransport()
    messages = [
        AgentMessage(role=MessageRole.SYSTEM, content="You are helpful"),
        AgentMessage(role=MessageRole.USER, content="Hello"),
    ]
    result = transport.format_messages(messages)
    assert len(result) == 2
    assert result[0]["role"] == "system"


def test_openai_transport_with_tool_calls() -> None:
    transport = OpenAITransport()
    msg = AgentMessage(
        role=MessageRole.ASSISTANT,
        content="",
        tool_calls=[ToolCall(id="tc_1", name="read", arguments={"path": "x.txt"})],
    )
    result = transport.format_messages([msg])
    assert "tool_calls" in result[0]
    assert result[0]["tool_calls"][0]["function"]["name"] == "read"


def test_anthropic_transport_format_messages() -> None:
    transport = AnthropicTransport()
    messages = [
        AgentMessage(role=MessageRole.SYSTEM, content="You are helpful"),
        AgentMessage(role=MessageRole.USER, content="Hello"),
    ]
    result = transport.format_messages(messages)
    assert len(result) >= 1


def test_transport_build_kwargs_openai() -> None:
    transport = OpenAITransport()
    kwargs = transport.build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        max_tokens=100,
    )
    assert "messages" in kwargs
    assert "max_tokens" in kwargs


def test_openai_parse_stream_text_only() -> None:
    transport = OpenAITransport()
    chunks = [
        json.dumps({"choices": [{"delta": {"content": "Hello"}}]}),
        json.dumps({"choices": [{"delta": {"content": " world"}}]}),
        "[DONE]",
    ]
    lines = [f"data: {c}" for c in chunks]
    response = _MockSSELines(lines)

    async def _run() -> list[TextStreamEvent]:
        events: list[TextStreamEvent] = []
        async for event in transport.parse_stream(response):
            if isinstance(event, TextStreamEvent):
                events.append(event)
        return events

    import asyncio

    events = asyncio.run(_run())

    assert len(events) == 2
    assert events[0].text == "Hello"
    assert events[1].text == " world"


def test_openai_parse_stream_tool_calls() -> None:
    transport = OpenAITransport()
    # Simulate tool_call deltas accumulating across multiple chunks,
    # then finish_reason == "tool_calls"
    chunks = [
        json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "tc_1",
                                    "function": {"name": "read_file", "arguments": ""},
                                }
                            ],
                        },
                    }
                ],
            }
        ),
        json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {"arguments": '{"path": "foo.txt"}'},
                                }
                            ],
                        },
                    }
                ],
            }
        ),
        json.dumps(
            {
                "choices": [
                    {
                        "delta": {},
                        "finish_reason": "tool_calls",
                    }
                ],
            }
        ),
    ]
    lines = [f"data: {c}" for c in chunks]
    response = _MockSSELines(lines)

    async def _run() -> list[ToolCallStreamEvent]:
        events: list[ToolCallStreamEvent] = []
        async for event in transport.parse_stream(response):
            if isinstance(event, ToolCallStreamEvent):
                events.append(event)
        return events

    import asyncio

    events = asyncio.run(_run())

    assert len(events) == 1
    tc = events[0].tool_call
    assert tc.id == "tc_1"
    assert tc.name == "read_file"
    assert tc.arguments == {"path": "foo.txt"}


def test_anthropic_parse_stream_text_only() -> None:
    transport = AnthropicTransport()
    # Simulate Anthropic-style SSE with event: and data: lines
    raw_lines = [
        "event: message_start",
        f"data: {json.dumps({'type': 'message_start'})}",
        "",
        "event: content_block_delta",
        f"data: {json.dumps({'delta': {'type': 'text_delta', 'text': 'Hello'}})}",
        "",
        "event: content_block_delta",
        f"data: {json.dumps({'delta': {'type': 'text_delta', 'text': ' world'}})}",
        "",
    ]
    response = _MockSSELines(raw_lines)

    async def _run() -> list[TextStreamEvent]:
        events: list[TextStreamEvent] = []
        async for event in transport.parse_stream(response):
            if isinstance(event, TextStreamEvent):
                events.append(event)
        return events

    import asyncio

    events = asyncio.run(_run())

    assert len(events) == 2
    assert events[0].text == "Hello"
    assert events[1].text == " world"


def test_transport_build_kwargs_anthropic_has_stream() -> None:
    transport = AnthropicTransport()
    kwargs = transport.build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
    )
    assert kwargs.get("stream") is True
