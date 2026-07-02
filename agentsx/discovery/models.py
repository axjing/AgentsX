"""Data models for discovered commands and skills.

Inspired by Claude Code's frontmatter-driven markdown definitions:
commands, agents, and skills are defined as .md files with YAML frontmatter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CommandArg:
    """A single argument for a discovered command."""

    name: str
    type: str = "string"
    required: bool = False
    description: str = ""


@dataclass
class DiscoveredCommand:
    """A slash command defined via a markdown file with YAML frontmatter.

    Format::

        ---
        name: review
        description: Review PR code
        arguments:
          - name: pr-number
            type: string
            required: true
        allowed_tools: ["Read", "Grep"]
        ---

        Step-by-step instructions...
    """

    name: str
    description: str
    instructions: str
    source_path: Path
    arguments: list[CommandArg] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    model: str = ""


@dataclass
class DiscoveredSkill:
    """A skill defined via a SKILL.md file.

    Inspired by Claude Code's three-level skill loading:
    1. Metadata (name + description) — always in context
    2. Body (<5K words) — loaded on trigger
    3. Bundled resources — loaded on demand

    Directory structure::

        skills/<skill-name>/
            SKILL.md        # Metadata + body
            references/     # Bundled resources (optional)
            scripts/        # Helper scripts (optional)
    """

    name: str
    description: str
    instructions: str
    source_path: Path
    version: str = "0.1.0"
    trigger_patterns: list[str] = field(default_factory=list)
    resource_dir: Path | None = None
