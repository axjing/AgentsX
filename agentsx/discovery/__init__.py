"""File-based discovery for commands and skills.

Inspired by Claude Code's convention-over-configuration approach:
put markdown files with YAML frontmatter in the right directories
and they auto-discover — no registration code needed.

Usage::

    from agentsx.discovery import discover_commands, discover_skills

    commands = discover_commands()
    for cmd in commands:
        print(f"  /{cmd.name} — {cmd.description}")

    skills = discover_skills()
    for sk in skills:
        print(f"  {sk.name} — {sk.description}")
"""

from __future__ import annotations

from agentsx.discovery.loader import discover_commands, discover_skills
from agentsx.discovery.models import (
    CommandArg,
    DiscoveredCommand,
    DiscoveredSkill,
)

__all__ = [
    "CommandArg",
    "DiscoveredCommand",
    "DiscoveredSkill",
    "discover_commands",
    "discover_skills",
]
