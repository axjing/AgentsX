"""Filesystem read-only tools."""

from __future__ import annotations

from pathlib import Path

from agentsx.tools import tool


@tool(description="Read a file from the local filesystem.")
def tool_file_read(path: str, offset: int = 0, limit: int = 0) -> str:
    """Read the contents of a file.

    Args:
        path: Absolute or relative path to the file.
        offset: Line number to start from (1-based). 0 = start.
        limit: Maximum lines to read. 0 = no limit.

    Returns:
        A string with line-number-prefixed content.
    """
    filepath = Path(path)
    if not filepath.exists():
        return f"Error: file not found: {path}"
    if not filepath.is_file():
        return f"Error: not a file: {path}"

    lines = filepath.read_text(encoding="utf-8").splitlines()
    if offset > 0:
        lines = lines[offset - 1 :]
    if limit > 0:
        lines = lines[:limit]

    start_num = offset if offset > 0 else 1
    return "\n".join(f"{i}: {line}" for i, line in enumerate(lines, start=start_num))


@tool(description="Search for files matching a glob pattern.")
def tool_file_glob(pattern: str, root: str = ".") -> str:
    matches = sorted(Path(root).glob(pattern))
    if not matches:
        return f"No files matching {pattern} in {root}"
    return "\n".join(str(m) for m in matches)


@tool(description="Search file contents using a regular expression.")
def tool_file_grep(
    pattern: str,
    include: str = "*.py",
    root: str = ".",
) -> str:
    import fnmatch
    import os
    import re

    root_path = Path(root)
    if not root_path.is_dir():
        return f"Error: not a directory: {root}"
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"Error: invalid regex: {exc}"
    matches: list[str] = []
    total = 0
    for filepath in root_path.rglob("*"):
        if not filepath.is_file():
            continue
        if not fnmatch.fnmatch(filepath.name, include):
            continue
        text = filepath.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                rel = os.path.relpath(filepath, root)
                matches.append(f"{rel}:{lineno}:{line}")
                total += 1
                if total >= 500:
                    break
        if total >= 500:
            break
    if not matches:
        return f"No matches for '{pattern}'"
    return "\n".join(matches)
