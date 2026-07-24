"""Context profile system for runtime posture detection."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

_SOURCE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".kts",
    ".scala",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".rb",
    ".swift",
    ".cs",
    ".fs",
    ".fsx",
    ".php",
    ".sh",
    ".lua",
    ".r",
    ".R",
    ".jl",
    ".dart",
    ".vue",
    ".svelte",
}

# Maximum number of directory entries to scan for source files.
_SCAN_MAX_ENTRIES = 50


class AgentPosture(str, Enum):
    """Represents the operational posture of the current working directory."""

    CODING = "coding"
    GENERAL = "general"


@dataclass(frozen=True)
class ContextProfile:
    """Immutable profile describing the agent's working context.

    Attributes:
        name: Human-readable profile identifier.
        posture: Detected operational posture.
        toolset_filter: Allowed tool names; empty means unrestricted.
        system_hint: Optional hint for system prompt construction.
    """

    name: str
    posture: AgentPosture
    toolset_filter: frozenset[str] = frozenset()
    system_hint: str = ""


_PROFILES: dict[str, ContextProfile] = {
    "coding": ContextProfile(
        name="coding",
        posture=AgentPosture.CODING,
        toolset_filter=frozenset({"read", "write", "exec", "orchestration"}),
        system_hint="You are working in a coding project.",
    ),
    "general": ContextProfile(
        name="general",
        posture=AgentPosture.GENERAL,
        toolset_filter=frozenset(),
        system_hint="",
    ),
}


def get_profile(name: str) -> ContextProfile | None:
    """Return the named profile, or None if not found.

    Args:
        name: Profile name to look up.

    Returns:
        The matching ContextProfile, or None.
    """
    return _PROFILES.get(name)


def _has_git_root(path: Path) -> bool:
    """Check whether *path* or any ancestor contains a .git directory.

    Args:
        path: Directory to start searching from.

    Returns:
        True if a .git directory is found in the ancestry.
    """
    for directory in [path] + list(path.parents):
        if (directory / ".git").is_dir():
            return True
    return False


def _has_source_files(path: Path) -> bool:
    """Check whether *path* contains any recognized source files.

    Scans at most ``_SCAN_MAX_ENTRIES`` entries across the directory tree
    to avoid expensive walks. Skips hidden (dot-prefixed) directories to
    avoid scanning .git, .venv, .mypy_cache, etc.

    Args:
        path: Directory to scan.

    Returns:
        True if at least one source file is found.
    """
    count = 0
    try:
        for entry in path.rglob("*"):
            # Skip hidden directories (e.g. .git, .venv, .mypy_cache)
            if any(part.startswith(".") for part in entry.parts):
                continue
            if count >= _SCAN_MAX_ENTRIES:
                break
            count += 1
            if entry.is_file() and entry.suffix in _SOURCE_EXTENSIONS:
                return True
    except PermissionError:
        return False
    return False


def resolve_runtime_mode(cwd: str | Path | None = None) -> ContextProfile:
    """Return the context profile for the given working directory.

    Returns the ``coding`` profile when *cwd* is inside a git repository
    that contains source files, otherwise returns ``general``.

    Args:
        cwd: Working directory path. Defaults to the current working
            directory.

    Returns:
        The resolved ContextProfile.
    """
    if cwd is None:
        cwd = Path.cwd()
    else:
        cwd = Path(cwd)

    if _has_git_root(cwd) and _has_source_files(cwd):
        return _PROFILES["coding"]
    return _PROFILES["general"]
