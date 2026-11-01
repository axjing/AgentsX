"""Tests for Autonomous Recursive Self-Improvement (RSI) crystallizer."""

from pathlib import Path

from agentsx.agent.crystallizer import AutonomousCrystallizer
from agentsx.protocol import ToolResult, ToolResultStatus


def test_crystallizer_bash_command_recovery(tmp_path: Path) -> None:
    crystallizer = AutonomousCrystallizer(workspace_root=tmp_path)

    # 1. Failed attempt: python3 not found
    err_res = ToolResult(
        tool_call_id="call_1",
        status=ToolResultStatus.ERROR,
        content="bash: python3: command not found",
    )
    res1 = crystallizer.record_tool_result(
        "tool_bash", {"command": "python3 script.py"}, err_res
    )
    assert res1 is None

    # 2. Successful recovery: python worked!
    ok_res = ToolResult(
        tool_call_id="call_2",
        status=ToolResultStatus.SUCCESS,
        content="success output",
    )
    res2 = crystallizer.record_tool_result(
        "tool_bash", {"command": "python script.py"}, ok_res
    )

    assert res2 is not None
    assert "Command 'python3' is unavailable on this host" in res2.rule
    assert "python" in res2.rule

    # Verify memory file was written
    memory_file = tmp_path / ".agentsx" / "memory.md"
    assert memory_file.is_file()
    content = memory_file.read_text(encoding="utf-8")
    expected = "- Command 'python3' is unavailable on this host; use 'python' instead."
    assert expected in content


def test_crystallizer_file_edit_ambiguity_recovery(tmp_path: Path) -> None:
    crystallizer = AutonomousCrystallizer(workspace_root=tmp_path)

    # 1. Failed edit: ambiguity
    err_res = ToolResult(
        tool_call_id="call_1",
        status=ToolResultStatus.ERROR,
        content="Error: old_string matches 3 locations in src/main.py",
    )
    res1 = crystallizer.record_tool_result(
        "tool_file_edit", {"path": "src/main.py", "old_string": "x = 1"}, err_res
    )
    assert res1 is None

    # 2. Successful recovery with more context
    ok_res = ToolResult(
        tool_call_id="call_2",
        status=ToolResultStatus.SUCCESS,
        content="Replaced 1 occurrence",
    )
    res2 = crystallizer.record_tool_result(
        "tool_file_edit",
        {"path": "src/main.py", "old_string": "def foo():\n    x = 1"},
        ok_res,
    )

    assert res2 is not None
    assert "When editing 'src/main.py'" in res2.rule
    assert "multi-match ambiguity" in res2.rule

    memory_file = tmp_path / ".agentsx" / "memory.md"
    assert memory_file.is_file()
    assert "multi-match ambiguity" in memory_file.read_text(encoding="utf-8")


def test_crystallizer_no_prior_failure_does_not_trigger(tmp_path: Path) -> None:
    crystallizer = AutonomousCrystallizer(workspace_root=tmp_path)
    ok_res = ToolResult(
        tool_call_id="call_1",
        status=ToolResultStatus.SUCCESS,
        content="success",
    )
    res = crystallizer.record_tool_result(
        "tool_bash", {"command": "git status"}, ok_res
    )
    assert res is None
    assert not (tmp_path / ".agentsx" / "memory.md").exists()
