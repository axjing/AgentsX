"""Tests for dynamic skill synthesis and discovery."""

import asyncio
import os
from pathlib import Path

from agentsx.tools import ToolRegistry
from agentsx.tools.builtin.orchestration.skills import (
    discover_skills,
    set_active_registry,
    tool_create_skill,
)


def test_tool_create_skill_invalid_identifier() -> None:
    res = tool_create_skill("not a valid name!", "def foo(): pass")
    assert "not a valid Python identifier" in res


def test_tool_create_skill_syntax_error() -> None:
    res = tool_create_skill("broken", "def foo(\n")
    assert "Syntax error in skill code" in res


def test_tool_create_skill_and_immediate_registration(
    tmp_path: Path, monkeypatch: None
) -> None:
    registry = ToolRegistry()
    set_active_registry(registry)

    # Change cwd to tmp_path
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        code = (
            "def calculate_tax(amount: float) -> float:\n"
            "    '''Calculate 10% tax on an amount.'''\n"
            "    return amount * 0.1\n"
        )
        res = tool_create_skill("calculate_tax", code, description="Compute 10% tax")
        assert "successfully" in res
        assert "skill_calculate_tax" in res

        # Verify tool is registered in registry!
        assert "skill_calculate_tax" in registry
        tool_spec = registry.get("skill_calculate_tax")
        assert tool_spec is not None
        assert "10% tax" in tool_spec.description

        # Execute the newly synthesized tool!
        call_res = asyncio.run(tool_spec.call(amount=100.0))
        assert call_res.is_success
        assert float(call_res.content) == 10.0
    finally:
        os.chdir(old_cwd)
        set_active_registry(None)


def test_discover_skills_from_directory(tmp_path: Path) -> None:
    skills_dir = tmp_path / ".agentsx" / "skills"
    skills_dir.mkdir(parents=True)

    skill_code = (
        "def custom_echo(text: str) -> str:\n"
        "    '''Echo custom string.'''\n"
        "    return f'custom: {text}'\n"
    )
    (skills_dir / "custom_echo.py").write_text(skill_code, encoding="utf-8")

    registry = ToolRegistry()
    discovered = discover_skills(registry, project_dir=tmp_path)

    assert "skill_custom_echo" in discovered
    assert "skill_custom_echo" in registry
