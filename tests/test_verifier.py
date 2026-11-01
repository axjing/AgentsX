"""Tests for proactive verification and quality gate."""

import json
from collections.abc import AsyncIterator
from pathlib import Path

from agentsx.agent.loop import run_agent_loop
from agentsx.agent.verifier import ProactiveQualityGate
from agentsx.protocol import (
    AgentMessage,
    MessageRole,
    TextStreamEvent,
    ToolCall,
    ToolCallStreamEvent,
)
from agentsx.provider import Model, Provider
from agentsx.tools import ToolRegistry, tool


def test_verify_python_valid(tmp_path: Path) -> None:
    gate = ProactiveQualityGate()
    valid_file = tmp_path / "test.py"
    valid_file.write_text("def hello() -> str:\n    return 'world'\n", encoding="utf-8")

    result = gate.verify_file(valid_file)
    assert result.is_valid
    assert result.file_type == "python"
    assert result.error_message == ""


def test_verify_python_syntax_error(tmp_path: Path) -> None:
    gate = ProactiveQualityGate()
    broken_file = tmp_path / "broken.py"
    broken_file.write_text("def hello(\n", encoding="utf-8")

    result = gate.verify_file(broken_file)
    assert not result.is_valid
    assert result.file_type == "python"
    assert "line 1" in result.error_message


def test_verify_json_valid(tmp_path: Path) -> None:
    gate = ProactiveQualityGate()
    valid_file = tmp_path / "data.json"
    valid_file.write_text(json.dumps({"key": "value"}), encoding="utf-8")

    result = gate.verify_file(valid_file)
    assert result.is_valid
    assert result.file_type == "json"


def test_verify_json_invalid(tmp_path: Path) -> None:
    gate = ProactiveQualityGate()
    broken_file = tmp_path / "broken.json"
    broken_file.write_text("{key: 'value'}", encoding="utf-8")

    result = gate.verify_file(broken_file)
    assert not result.is_valid
    assert result.file_type == "json"
    assert "line 1" in result.error_message


def test_verify_tool_call_write(tmp_path: Path) -> None:
    gate = ProactiveQualityGate()
    target = tmp_path / "script.py"
    target.write_text("def bad():\n  pass\n", encoding="utf-8")

    res = gate.verify_tool_call("tool_file_write", {"path": str(target)})
    assert res is not None
    assert res.is_valid

    # Non-modifying tool should return None
    assert gate.verify_tool_call("tool_file_read", {"path": str(target)}) is None


def test_verify_nonexistent_file(tmp_path: Path) -> None:
    gate = ProactiveQualityGate()
    result = gate.verify_file(tmp_path / "missing.py")
    assert result.is_valid
    assert result.file_type == "unknown"


async def test_quality_gate_loop_integration(tmp_path: Path) -> None:
    """Test that loop automatically injects quality gate alert on syntax error."""
    broken_py = tmp_path / "broken.py"

    @tool(description="Write file")
    def tool_file_write(path: str, content: str) -> str:
        Path(path).write_text(content, encoding="utf-8")
        return "ok"

    tools = ToolRegistry()
    tools.register(tool_file_write)

    class MockProvider(Provider):
        def __init__(self) -> None:
            super().__init__(Model("mock", "mock", 1000))
            self.turn = 0

        def format_messages(
            self, messages: list[AgentMessage]
        ) -> list[dict[str, object]]:
            return []

        async def stream(
            self, messages: list[AgentMessage]
        ) -> AsyncIterator[TextStreamEvent | ToolCallStreamEvent]:
            self.turn += 1
            if self.turn == 1:
                yield ToolCallStreamEvent(
                    tool_call=ToolCall(
                        id="call_1",
                        name="tool_file_write",
                        arguments={"path": str(broken_py), "content": "def broken(\n"},
                    )
                )
            else:
                yield TextStreamEvent(text="Done")

    provider = MockProvider()
    messages = [AgentMessage(role=MessageRole.USER, content="write broken code")]

    events = [event async for event in run_agent_loop(provider, messages, tools=tools)]
    assert events

    # Check that quality gate alert was injected into messages
    alert_msgs = [m for m in messages if "[Proactive Quality Gate Alert]" in m.content]
    assert len(alert_msgs) == 1
    assert "broken.py" in alert_msgs[0].content
