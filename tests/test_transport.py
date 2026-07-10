"""Tests for the provider transport abstraction layer."""

from agentsx.core.types import (
    AgentMessage,
    MessageRole,
    ToolCall,
)
from agentsx.provider.transport import AnthropicTransport, OpenAITransport


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
