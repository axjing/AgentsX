"""Memory tool for saving persistent project rules and lessons.

Inspired by Claude Code CLAUDE.md / Memory crystallization.
"""

from pathlib import Path

from agentsx.tools import TOOLSET_ORCHESTRATION, tool


def _get_memory_path(scope: str) -> Path:
    """Resolve the memory markdown file path according to scope."""
    if scope.strip().lower() == "global":
        return Path.home() / ".agentsx" / "memory.md"
    return Path.cwd() / ".agentsx" / "memory.md"


@tool(
    description="Save a key project convention, rule, or learned lesson to memory.",
    toolset=TOOLSET_ORCHESTRATION,
)
def tool_remember(fact: str, scope: str = "project") -> str:
    """Save a persistent rule or lesson to memory.

    Args:
        fact: The validated rule, fact, or guideline to remember.
        scope: Storage scope, either ``"project"`` (default) or ``"global"``.

    Returns:
        Operation confirmation message.
    """
    clean_fact = fact.strip()
    if not clean_fact:
        return "Error: Empty fact cannot be recorded."

    norm_scope = scope.strip().lower()
    if norm_scope not in ("project", "global"):
        return f"Error: Unknown scope '{scope}'. Use 'project' or 'global'."

    target_path = _get_memory_path(norm_scope)
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return f"Error creating directory for memory: {exc}"

    existing_lines: list[str] = []
    if target_path.is_file():
        try:
            existing_lines = target_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            return f"Error reading existing memory file: {exc}"

    fact_line = f"- {clean_fact}"
    # Avoid duplicate lines
    if fact_line in existing_lines:
        return f"Already remembered in {target_path}: '{clean_fact}'"

    try:
        with target_path.open("a", encoding="utf-8") as f:
            if existing_lines and not existing_lines[-1].endswith("\n"):
                f.write("\n")
            f.write(f"{fact_line}\n")
    except OSError as exc:
        return f"Error writing to memory file: {exc}"

    return f"Remembered in {target_path}: '{clean_fact}'"
