"""Frontmatter parser and directory scanner for commands and skills.

Inspired by Claude Code's file-system-based plugin discovery:
put .md files in the right directories and they auto-discover.
"""

import logging
import re
from pathlib import Path
from typing import Any

from agentsx.config import get_settings
from agentsx.discovery.models import CommandArg, DiscoveredCommand, DiscoveredSkill

logger = logging.getLogger(__name__)

# ── Frontmatter parser ──────────────────────────────────────

_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n(.*)",
    re.DOTALL,
)


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a markdown file.

    Args:
        content: Raw file content.

    Returns:
        A tuple of (frontmatter_dict, body_text).
        Returns ({}, content) if no frontmatter is found.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}, content

    raw_frontmatter = match.group(1)
    body = match.group(2).strip()

    parsed: dict[str, Any] = {}
    current_list_key: str | None = None

    for line in raw_frontmatter.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- "):
            item = stripped[2:].strip().strip('"').strip("'")
            if current_list_key:
                if not isinstance(parsed.get(current_list_key), list):
                    parsed[current_list_key] = []
                parsed[current_list_key].append(item)
            continue

        if ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not value:
                current_list_key = key
                parsed[key] = []
            else:
                current_list_key = None
                if value.lower() in ("true", "yes"):
                    parsed[key] = True
                elif value.lower() in ("false", "no"):
                    parsed[key] = False
                elif value.startswith("[") and value.endswith("]"):
                    items = [
                        x.strip().strip('"').strip("'")
                        for x in value[1:-1].split(",")
                        if x.strip()
                    ]
                    parsed[key] = items
                else:
                    parsed[key] = value

    return parsed, body


def _parse_list_field(data: dict[str, Any], field: str) -> None:
    """Parse a YAML list-like field from frontmatter."""
    raw = data.get(field)
    if raw is None:
        return
    if isinstance(raw, list):
        return
    if isinstance(raw, str):
        items = []
        for item in raw.split("\n"):
            item = item.strip().strip("-").strip()
            if item:
                items.append(item)
        data[field] = items


# ── Directory scanners ──────────────────────────────────────


def scan_commands(base_dir: Path) -> list[DiscoveredCommand]:
    """Scan a directory for command markdown files.

    Scans ``*.md`` files in the given directory. Each file should
    have YAML frontmatter with at minimum ``name`` and ``description``.

    Args:
        base_dir: Directory to scan (e.g. ``~/.agentsx/commands/``).

    Returns:
        A list of discovered commands.
    """
    if not base_dir.is_dir():
        return []

    commands: list[DiscoveredCommand] = []
    for path in sorted(base_dir.iterdir()):
        if path.suffix != ".md":
            continue
        try:
            content = path.read_text(encoding="utf-8")
            front, body = parse_frontmatter(content)
            name = front.get("name", path.stem)
            description = front.get("description", "")
            if not description:
                logger.debug("Skipping %s: no description", path)
                continue

            args_raw = front.get("arguments", [])
            arguments = []
            if isinstance(args_raw, list):
                for arg_item in args_raw:
                    if isinstance(arg_item, dict):
                        arguments.append(
                            CommandArg(
                                name=arg_item.get("name", ""),
                                type=arg_item.get("type", "string"),
                                required=arg_item.get("required", False),
                                description=arg_item.get("description", ""),
                            ),
                        )
                    elif isinstance(arg_item, str):
                        arguments.append(CommandArg(name=arg_item))

            allowed_tools = front.get("allowed_tools", [])
            if isinstance(allowed_tools, str):
                allowed_tools = [allowed_tools]

            commands.append(
                DiscoveredCommand(
                    name=name,
                    description=description,
                    instructions=body,
                    source_path=path,
                    arguments=arguments,
                    allowed_tools=allowed_tools or [],
                    model=front.get("model", ""),
                ),
            )
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Failed to read command %s: %s", path, exc)

    return commands


def scan_skills(base_dir: Path) -> list[DiscoveredSkill]:
    """Scan a directory for skill definitions.

    Looks for ``SKILL.md`` files in subdirectories of *base_dir*::

        skills/
            code-review/
                SKILL.md
                references/
                scripts/

    Args:
        base_dir: Directory to scan (e.g. ``~/.agentsx/skills/``).

    Returns:
        A list of discovered skills.
    """
    if not base_dir.is_dir():
        return []

    skills: list[DiscoveredSkill] = []
    for entry in sorted(base_dir.iterdir()):
        if not entry.is_dir():
            continue
        skill_file = entry / "SKILL.md"
        if not skill_file.is_file():
            continue
        try:
            content = skill_file.read_text(encoding="utf-8")
            front, body = parse_frontmatter(content)
            name = front.get("name", entry.name)
            description = front.get("description", "")
            if not description:
                logger.debug("Skipping skill %s: no description", entry.name)
                continue

            trigger_patterns = front.get("trigger_patterns", [])
            if isinstance(trigger_patterns, str):
                trigger_patterns = [trigger_patterns]

            ref_path = entry / "references"
            resource_dir: Path | None = ref_path if ref_path.is_dir() else None

            skills.append(
                DiscoveredSkill(
                    name=name,
                    description=description,
                    instructions=body,
                    source_path=skill_file,
                    version=str(front.get("version", "0.1.0")),
                    trigger_patterns=trigger_patterns,
                    resource_dir=resource_dir,
                ),
            )
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Failed to read skill %s: %s", entry.name, exc)

    return skills


# ── Aggregated discovery ────────────────────────────────────


def discover_commands() -> list[DiscoveredCommand]:
    """Discover commands from all standard locations.

    Search order (later overrides earlier):
    1. User global: ``~/.agentsx/commands/``
    2. Project local: ``<cwd>/.agentsx/commands/``
    """
    settings = get_settings()
    base = Path(settings.discovery_dir or Path.home() / ".agentsx")

    user_commands: dict[str, DiscoveredCommand] = {
        cmd.name: cmd for cmd in scan_commands(base / "commands")
    }

    project_dir = Path.cwd() / ".agentsx" / "commands"
    project_commands: dict[str, DiscoveredCommand] = (
        {cmd.name: cmd for cmd in scan_commands(project_dir)}
        if project_dir.is_dir()
        else {}
    )

    merged = {**user_commands, **project_commands}
    return list(merged.values())


def discover_skills() -> list[DiscoveredSkill]:
    """Discover skills from all standard locations.

    Search order (later overrides earlier):
    1. User global: ``~/.agentsx/skills/``
    2. Project local: ``<cwd>/.agentsx/skills/``
    """
    settings = get_settings()
    base = Path(settings.discovery_dir or Path.home() / ".agentsx")

    user_skills: dict[str, DiscoveredSkill] = {
        sk.name: sk for sk in scan_skills(base / "skills")
    }

    project_dir = Path.cwd() / ".agentsx" / "skills"
    project_skills: dict[str, DiscoveredSkill] = (
        {sk.name: sk for sk in scan_skills(project_dir)} if project_dir.is_dir() else {}
    )

    merged = {**user_skills, **project_skills}
    return list(merged.values())
