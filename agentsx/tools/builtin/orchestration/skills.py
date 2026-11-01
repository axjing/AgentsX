"""Dynamic skill synthesis and discovery for Recursive Self-Improvement.

Allows agents to synthesize new reusable Python tools into ``.agentsx/skills/``
and dynamically load and register them into the active ToolRegistry.
"""

import ast
import importlib.util
import logging
from pathlib import Path
from types import ModuleType

from agentsx.tools import TOOLSET_ORCHESTRATION, ToolRegistry, ToolSpec, tool

logger = logging.getLogger(__name__)

# Module-level reference to the active session registry
_ACTIVE_REGISTRY: ToolRegistry | None = None


def set_active_registry(registry: ToolRegistry | None) -> None:
    """Set the active ToolRegistry for immediate dynamic tool registration."""
    global _ACTIVE_REGISTRY
    _ACTIVE_REGISTRY = registry


def get_active_registry() -> ToolRegistry | None:
    """Return the currently active ToolRegistry."""
    return _ACTIVE_REGISTRY


def _resolve_skill_dir(scope: str, project_dir: Path | None = None) -> Path:
    """Resolve directory for skills based on scope."""
    if scope.strip().lower() == "global":
        return Path.home() / ".agentsx" / "skills"
    base = project_dir or Path.cwd()
    return base / ".agentsx" / "skills"


def _load_module_from_path(name: str, path: Path) -> ModuleType:
    """Dynamically load a Python module from a file path."""
    spec = importlib.util.spec_from_file_location(f"agentsx_skill_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load spec from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _register_module_functions(
    registry: ToolRegistry,
    name: str,
    module: ModuleType,
    description: str = "",
) -> bool:
    """Find and register suitable functions from a skill module."""
    # 1. Prefer function matching skill name
    target_fn = getattr(module, name, None)
    if target_fn is None or not callable(target_fn):
        # 2. Pick first callable non-private function
        for attr_name, attr_val in vars(module).items():
            if not attr_name.startswith("_") and callable(attr_val):
                target_fn = attr_val
                name = attr_name
                break

    if target_fn is None or not callable(target_fn):
        return False

    doc = description or getattr(target_fn, "__doc__", "") or f"Custom skill {name}"
    tool_name = name if name.startswith("skill_") else f"skill_{name}"

    spec = ToolSpec(
        name=tool_name,
        description=doc.strip(),
        fn=target_fn,
        toolset=TOOLSET_ORCHESTRATION,
    )
    registry.register(spec)
    return True


@tool(
    description="Synthesize a new Python skill and register it as a tool.",
    toolset=TOOLSET_ORCHESTRATION,
)
def tool_create_skill(
    name: str,
    code: str,
    description: str = "",
    scope: str = "project",
) -> str:
    """Synthesize a new Python skill and immediately register it as a tool.

    Args:
        name: Name of the skill (valid Python identifier).
        code: Complete Python source code implementing the skill function.
        description: Brief description of what the skill does.
        scope: Storage scope, either ``"project"`` or ``"global"``.

    Returns:
        Confirmation message with registration status.
    """
    clean_name = name.strip()
    if not clean_name.isidentifier():
        return f"Error: '{name}' is not a valid Python identifier."

    # Validate Python syntax before saving
    try:
        ast.parse(code, filename=f"<skill_{clean_name}>")
    except SyntaxError as exc:
        return f"Error: Syntax error in skill code: {exc}"

    target_dir = _resolve_skill_dir(scope)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / f"{clean_name}.py"
        file_path.write_text(code, encoding="utf-8")
    except OSError as exc:
        return f"Error saving skill file: {exc}"

    # Try dynamic load & registration
    try:
        module = _load_module_from_path(clean_name, file_path)
    except Exception as exc:  # noqa: BLE001
        return f"Skill file saved to {file_path}, but loading failed: {exc}"

    registered = False
    active_reg = get_active_registry()
    if active_reg is not None:
        registered = _register_module_functions(
            active_reg, clean_name, module, description
        )

    registered_msg = (
        f"and registered as 'skill_{clean_name}'"
        if registered
        else "saved (will load on next restart)"
    )
    return f"Skill '{clean_name}' successfully {registered_msg} at {file_path}."


def discover_skills(
    registry: ToolRegistry,
    project_dir: Path | None = None,
) -> list[str]:
    """Discover custom skill modules from project and global directories.

    Args:
        registry: The ToolRegistry to register discovered skills into.
        project_dir: Optional workspace root directory.

    Returns:
        List of registered skill tool names.
    """
    set_active_registry(registry)
    dirs_to_scan = [
        _resolve_skill_dir("global"),
        _resolve_skill_dir("project", project_dir),
    ]

    discovered: list[str] = []
    for s_dir in dirs_to_scan:
        if not s_dir.is_dir():
            continue

        for py_file in s_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            skill_name = py_file.stem
            try:
                module = _load_module_from_path(skill_name, py_file)
                if _register_module_functions(registry, skill_name, module):
                    tool_name = (
                        skill_name
                        if skill_name.startswith("skill_")
                        else f"skill_{skill_name}"
                    )
                    discovered.append(tool_name)
                    logger.info("Discovered skill '%s' from %s", tool_name, py_file)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to load skill %s: %s", py_file, exc)

    return discovered
