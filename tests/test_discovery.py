"""Tests for file-based command and skill discovery (``agentsx/discovery/``)."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from agentsx.discovery.loader import (
    discover_commands,
    discover_skills,
    parse_frontmatter,
    scan_commands,
    scan_skills,
)


class TestParseFrontmatter:
    """Test YAML frontmatter extraction and parsing."""

    def test_no_frontmatter(self) -> None:
        content = "# Just a header\nSome body text."
        front, body = parse_frontmatter(content)
        assert front == {}
        assert body == content

    def test_standard_frontmatter(self) -> None:
        content = """---
name: test-command
description: A command for testing
model: claude-3-5-sonnet
---
# Instructions
Do something useful.
"""
        front, body = parse_frontmatter(content)
        assert front["name"] == "test-command"
        assert front["description"] == "A command for testing"
        assert front["model"] == "claude-3-5-sonnet"
        assert body == "# Instructions\nDo something useful."

    def test_booleans_and_comments(self) -> None:
        content = """---
name: sample
# This is a comment
enabled: true
active: yes
disabled: false
inactive: no
---
Body text
"""
        front, body = parse_frontmatter(content)
        assert front["name"] == "sample"
        assert front["enabled"] is True
        assert front["active"] is True
        assert front["disabled"] is False
        assert front["inactive"] is False
        assert body == "Body text"

    def test_list_fields_parsing(self) -> None:
        content = """---
name: review
description: Code review
allowed_tools:
  - tool_file_read
  - tool_file_grep
trigger_patterns:
  - review
  - check code
---
Review body
"""
        front, body = parse_frontmatter(content)
        assert front["allowed_tools"] == ["tool_file_read", "tool_file_grep"]
        assert front["trigger_patterns"] == ["review", "check code"]


class TestScanCommands:
    """Test scanning directories for command definitions."""

    def test_nonexistent_dir(self) -> None:
        assert scan_commands(Path("/nonexistent/dir")) == []

    def test_scan_valid_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            cmd_file = base / "review.md"
            cmd_file.write_text(
                """---
name: code-review
description: Run automated code review
model: gpt-4o
allowed_tools:
  - tool_file_read
---
Please review all staged files.
""",
                encoding="utf-8",
            )
            # Create a file missing description (should be skipped)
            ignored = base / "ignored.md"
            ignored.write_text(
                """---
name: no-desc
---
Instructions
""",
                encoding="utf-8",
            )
            # Create a non-md file
            non_md = base / "notes.txt"
            non_md.write_text("Hello", encoding="utf-8")

            commands = scan_commands(base)
            assert len(commands) == 1
            cmd = commands[0]
            assert cmd.name == "code-review"
            assert cmd.description == "Run automated code review"
            assert cmd.model == "gpt-4o"
            assert cmd.allowed_tools == ["tool_file_read"]
            assert "Please review all staged files." in cmd.instructions
            assert cmd.source_path == cmd_file

    def test_command_with_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            cmd_file = base / "deploy.md"
            cmd_file.write_text(
                """---
name: deploy
description: Deploy service
arguments:
  - env
  - target
---
Deploy to environment.
""",
                encoding="utf-8",
            )
            commands = scan_commands(base)
            assert len(commands) == 1
            args = commands[0].arguments
            assert len(args) == 2
            assert args[0].name == "env"
            assert args[1].name == "target"


class TestScanSkills:
    """Test scanning directories for skill definitions."""

    def test_nonexistent_dir(self) -> None:
        assert scan_skills(Path("/nonexistent/dir")) == []

    def test_scan_skill_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            skill_dir = base / "git-helper"
            skill_dir.mkdir()
            skill_file = skill_dir / "SKILL.md"
            skill_file.write_text(
                """---
name: git-expert
description: Git command helper
version: 1.2.0
trigger_patterns:
  - git status
  - git commit
---
Help users with complex git workflows.
""",
                encoding="utf-8",
            )
            # Optional references dir
            ref_dir = skill_dir / "references"
            ref_dir.mkdir()

            skills = scan_skills(base)
            assert len(skills) == 1
            skill = skills[0]
            assert skill.name == "git-expert"
            assert skill.description == "Git command helper"
            assert skill.version == "1.2.0"
            assert skill.trigger_patterns == ["git status", "git commit"]
            assert skill.resource_dir == ref_dir
            assert "Help users with complex git workflows." in skill.instructions


class TestDiscoverAggregated:
    """Test discover_commands and discover_skills precedence."""

    def test_project_overrides_user_command(self) -> None:
        with tempfile.TemporaryDirectory() as user_tmp:
            with tempfile.TemporaryDirectory() as proj_tmp:
                user_base = Path(user_tmp)
                user_cmds = user_base / "commands"
                user_cmds.mkdir()
                (user_cmds / "test.md").write_text(
                    """---
name: test
description: User global version
---
Global body
""",
                    encoding="utf-8",
                )

                proj_base = Path(proj_tmp)
                proj_cmds = proj_base / ".agentsx" / "commands"
                proj_cmds.mkdir(parents=True)
                (proj_cmds / "test.md").write_text(
                    """---
name: test
description: Project local override
---
Project body
""",
                    encoding="utf-8",
                )

                with patch("agentsx.discovery.loader.get_settings") as mock_settings:
                    mock_settings.return_value.discovery_dir = str(user_base)
                    with patch("pathlib.Path.cwd", return_value=proj_base):
                        commands = discover_commands()
                        assert len(commands) == 1
                        assert commands[0].description == "Project local override"
                        assert "Project body" in commands[0].instructions

    def test_project_overrides_user_skill(self) -> None:
        with tempfile.TemporaryDirectory() as user_tmp:
            with tempfile.TemporaryDirectory() as proj_tmp:
                user_base = Path(user_tmp)
                user_skills = user_base / "skills" / "my-skill"
                user_skills.mkdir(parents=True)
                (user_skills / "SKILL.md").write_text(
                    """---
name: my-skill
description: Global skill
---
Global instructions
""",
                    encoding="utf-8",
                )

                proj_base = Path(proj_tmp)
                proj_skills = proj_base / ".agentsx" / "skills" / "my-skill"
                proj_skills.mkdir(parents=True)
                (proj_skills / "SKILL.md").write_text(
                    """---
name: my-skill
description: Project skill
---
Project instructions
""",
                    encoding="utf-8",
                )

                with patch("agentsx.discovery.loader.get_settings") as mock_settings:
                    mock_settings.return_value.discovery_dir = str(user_base)
                    with patch("pathlib.Path.cwd", return_value=proj_base):
                        skills = discover_skills()
                        assert len(skills) == 1
                        assert skills[0].description == "Project skill"
                        assert "Project instructions" in skills[0].instructions
