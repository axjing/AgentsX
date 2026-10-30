"""Tests for RSI memory crystallization tool and harness injection."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agentsx.agent.harness import AgentHarness
from agentsx.protocol.messages import MessageRole
from agentsx.tools.builtin.orchestration.memory import tool_remember


def test_tool_remember_project_scope(tmp_path: Path, monkeypatch: object) -> None:
    """Test recording a fact into project-level memory.md."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)  # type: ignore[attr-defined]

    fact = "Always use (str, Enum) mixin instead of StrEnum."
    result = tool_remember.fn(fact, scope="project")

    assert "Remembered in" in result
    assert fact in result

    mem_file = tmp_path / ".agentsx" / "memory.md"
    assert mem_file.is_file()
    content = mem_file.read_text(encoding="utf-8")
    assert f"- {fact}" in content


def test_tool_remember_duplicate_suppression(
    tmp_path: Path, monkeypatch: object
) -> None:
    """Test duplicate facts are detected and not appended again."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)  # type: ignore[attr-defined]

    fact = "Use ruff format for code formatting."
    res1 = tool_remember.fn(fact, scope="project")
    assert "Remembered in" in res1

    res2 = tool_remember.fn(fact, scope="project")
    assert "Already remembered" in res2

    mem_file = tmp_path / ".agentsx" / "memory.md"
    content = mem_file.read_text(encoding="utf-8")
    assert content.count(fact) == 1


def test_tool_remember_global_scope(tmp_path: Path, monkeypatch: object) -> None:
    """Test recording a fact into user global memory.md."""
    home_dir = tmp_path / "fake_home"
    home_dir.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home_dir)  # type: ignore[attr-defined]

    fact = "User prefers concise answers without emoji."
    result = tool_remember.fn(fact, scope="global")

    assert "Remembered in" in result
    mem_file = home_dir / ".agentsx" / "memory.md"
    assert mem_file.is_file()
    content = mem_file.read_text(encoding="utf-8")
    assert f"- {fact}" in content


def test_tool_remember_empty_fact(tmp_path: Path) -> None:
    """Test empty or blank fact is rejected."""
    result = tool_remember.fn("   ")
    assert "Empty fact" in result


def test_tool_remember_invalid_scope(tmp_path: Path) -> None:
    """Test invalid scope returns error message."""
    result = tool_remember.fn("Valid fact", scope="cluster")
    assert "Unknown scope 'cluster'" in result


@pytest.mark.asyncio
async def test_tool_remember_spec_call(tmp_path: Path, monkeypatch: object) -> None:
    """Test ToolSpec.call() integration returning ToolResult."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)  # type: ignore[attr-defined]

    fact = "Async tool execution works."
    res = await tool_remember.call(fact=fact)
    assert not res.is_error
    assert "Remembered in" in res.content


def test_harness_injects_persistent_memory(tmp_path: Path, monkeypatch: object) -> None:
    """Test AgentHarness automatically loads and injects persistent memory."""
    # Setup project memory
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.setattr(Path, "cwd", lambda: project_dir)  # type: ignore[attr-defined]

    proj_mem = project_dir / ".agentsx" / "memory.md"
    proj_mem.parent.mkdir(parents=True)
    proj_mem.write_text("- Never use bare except clauses.\n", encoding="utf-8")

    # Setup global memory
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home_dir)  # type: ignore[attr-defined]

    glob_mem = home_dir / ".agentsx" / "memory.md"
    glob_mem.parent.mkdir(parents=True)
    glob_mem.write_text("- Format output as concise markdown.\n", encoding="utf-8")

    mock_provider = MagicMock()
    harness = AgentHarness(provider=mock_provider)

    # Check system message in harness
    system_msg = harness.messages[0]
    assert system_msg.role == MessageRole.SYSTEM
    assert "## Project Memory & Learned Rules:" in system_msg.content
    assert "- Never use bare except clauses." in system_msg.content
    assert "## Global Learned Rules:" in system_msg.content
    assert "- Format output as concise markdown." in system_msg.content
