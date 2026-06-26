"""Tests for core data types."""

from __future__ import annotations

from datetime import datetime

from agentsx.core.types import (
    AgentEvent,
    AgentMessage,
    Decision,
    ErrorEvent,
    MessageRole,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCall,
    ToolExecutionEvent,
    ToolResult,
)


class TestMessageRole:
    def test_values(self):
        assert MessageRole.SYSTEM.value == "system"
        assert MessageRole.USER.value == "user"
        assert MessageRole.ASSISTANT.value == "assistant"
        assert MessageRole.TOOL.value == "tool"

    def test_is_string_enum(self):
        assert isinstance(MessageRole.SYSTEM, str)


class TestToolCall:
    def test_creation(self):
        tc = ToolCall(
            id="call_1",
            name="read_file",
            arguments={"path": "/tmp/test.txt"},
        )
        assert tc.id == "call_1"
        assert tc.name == "read_file"
        assert tc.arguments == {"path": "/tmp/test.txt"}


class TestToolResult:
    def test_creation(self):
        tr = ToolResult(
            id="res_1",
            tool_call_id="call_1",
            content="file content",
            is_error=False,
        )
        assert tr.id == "res_1"
        assert tr.tool_call_id == "call_1"
        assert tr.content == "file content"
        assert not tr.is_error

    def test_error_default(self):
        tr = ToolResult(id="res_1", tool_call_id="call_1", content="error")
        assert not tr.is_error

    def test_explicit_error(self):
        tr = ToolResult(
            id="res_1",
            tool_call_id="call_1",
            content="error",
            is_error=True,
        )
        assert tr.is_error


class TestAgentMessage:
    def test_user_message(self):
        msg = AgentMessage(role=MessageRole.USER, content="Hello")
        assert msg.role == MessageRole.USER
        assert msg.content == "Hello"
        assert msg.tool_calls is None

    def test_system_message(self):
        msg = AgentMessage(role=MessageRole.SYSTEM, content="You are helpful.")
        assert msg.role == MessageRole.SYSTEM

    def test_message_has_id(self):
        msg1 = AgentMessage(role=MessageRole.USER, content="Hi")
        msg2 = AgentMessage(role=MessageRole.USER, content="Hi")
        assert msg1.id != msg2.id

    def test_convert_to_openai_user(self):
        msg = AgentMessage(role=MessageRole.USER, content="Hello")
        result = msg.convert_to_provider("openai")
        assert result["role"] == "user"
        assert result["content"] == "Hello"

    def test_convert_to_openai_tool_result(self):
        tc = ToolCall(id="call_1", name="read_file", arguments={"path": "test.txt"})
        msg = AgentMessage(
            role=MessageRole.TOOL,
            content="file content",
            tool_calls=[tc],
        )
        result = msg.convert_to_provider("openai")
        assert result["role"] == "tool"
        assert result["content"] == "file content"

    def test_convert_to_openai_with_tool_calls(self):
        tc = ToolCall(id="call_1", name="read_file", arguments={"path": "test.txt"})
        msg = AgentMessage(
            role=MessageRole.ASSISTANT,
            content="Let me read that file",
            tool_calls=[tc],
        )
        result = msg.convert_to_provider("openai")
        assert result["role"] == "assistant"
        assert "tool_calls" in result
        assert result["tool_calls"][0]["function"]["name"] == "read_file"

    def test_convert_to_anthropic_user(self):
        msg = AgentMessage(role=MessageRole.USER, content="Hello")
        result = msg.convert_to_provider("anthropic")
        assert result["role"] == "user"
        assert result["content"] == "Hello"

    def test_convert_to_anthropic_tool_use(self):
        tc = ToolCall(id="call_1", name="read_file", arguments={"path": "test.txt"})
        msg = AgentMessage(
            role=MessageRole.ASSISTANT,
            content="Let me read that",
            tool_calls=[tc],
        )
        result = msg.convert_to_provider("anthropic")
        assert result["role"] == "assistant"
        content = result["content"]
        assert isinstance(content, list)
        assert any(block["type"] == "tool_use" for block in content)

    def test_convert_to_unknown_provider(self):
        msg = AgentMessage(role=MessageRole.USER, content="Hello")
        import pytest

        with pytest.raises(ValueError, match="Unknown provider"):
            msg.convert_to_provider("unknown")


class TestEvents:
    def test_model_request_event(self):
        msgs = [AgentMessage(role=MessageRole.USER, content="Hi")]
        event = ModelRequestEvent(messages=msgs, model="gpt-4o")
        assert event.model == "gpt-4o"
        assert len(event.messages) == 1
        assert isinstance(event.timestamp, datetime)

    def test_model_response_event(self):
        event = ModelResponseEvent(content="Hello", usage={"total_tokens": 10})
        assert event.content == "Hello"
        assert event.usage == {"total_tokens": 10}

    def test_model_response_tokens_default(self):
        event = ModelResponseEvent(content="Hello")
        assert event.usage is None

    def test_tool_execution_event(self):
        tc = ToolCall(id="call_1", name="read_file", arguments={})
        tr = ToolResult(id="res_1", tool_call_id="call_1", content="data")
        event = ToolExecutionEvent(tool_call=tc, result=tr)
        assert event.tool_call.name == "read_file"
        assert event.result.content == "data"

    def test_error_event(self):
        error = ValueError("something went wrong")
        event = ErrorEvent(error=error, context="test")
        assert isinstance(event.error, ValueError)
        assert event.context == "test"

    def test_agent_event_is_union(self):
        """AgentEvent should accept all event types via isinstance check."""
        events: list[AgentEvent] = [
            ModelRequestEvent(messages=[], model="test"),
            ModelResponseEvent(content="hi"),
            ToolExecutionEvent(
                tool_call=ToolCall(id="c1", name="t", arguments={}),
                result=ToolResult(id="r1", tool_call_id="c1", content="ok"),
            ),
            ErrorEvent(error=ValueError("e"), context="ctx"),
        ]
        assert len(events) == 4
        assert isinstance(events[0], ModelRequestEvent)
        assert isinstance(events[1], ModelResponseEvent)
        assert isinstance(events[2], ToolExecutionEvent)
        assert isinstance(events[3], ErrorEvent)


class TestDecision:
    def test_values(self):
        assert Decision.ALLOW.value == "allow"
        assert Decision.PROMPT.value == "prompt"
        assert Decision.FORBIDDEN.value == "forbidden"

    def test_is_string_enum(self):
        assert isinstance(Decision.ALLOW, str)
