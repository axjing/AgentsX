"""Filesystem read/write/edit/search tools."""

from __future__ import annotations

import re
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


@tool(description="Write content to a file (overwrite or create).")
def tool_file_write(path: str, content: str) -> str:
    """Write content to a file. Creates parent directories if needed.

    Args:
        path: File path.
        content: Content to write.

    Returns:
        Confirmation message with byte count.
    """
    filepath = Path(path)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    written = filepath.write_text(content, encoding="utf-8")
    return f"Wrote {written} bytes to {path}"


@tool(description="Edit an existing file by performing an exact-text replacement.")
def tool_file_edit(
    path: str,
    old_string: str,
    new_string: str,
) -> str:
    """Replace *old_string* with *new_string* in a file.

    Args:
        path: File path.
        old_string: Text to find (must match exactly).
        new_string: Replacement text.

    Returns:
        Confirmation or error message.
    """
    filepath = Path(path)
    if not filepath.exists():
        return f"Error: file not found: {path}"

    text = filepath.read_text(encoding="utf-8")
    if old_string not in text:
        return f"Error: old_string not found in {path}"

    new_text = text.replace(old_string, new_string)
    filepath.write_text(new_text, encoding="utf-8")
    old_len = len(old_string)
    new_len = len(new_string)
    return f"Edited {path}: replaced {old_len} chars with {new_len} chars"


@tool(description="Search for files matching a glob pattern.")
def tool_file_glob(pattern: str, root: str = ".") -> str:
    """Search for files matching a glob pattern.

    Args:
        pattern: Glob pattern (e.g. ``**/*.py``).
        root: Root directory to search from.

    Returns:
        Matching file paths, one per line.
    """
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
    """Search file contents with a regex.

    Uses Python's built-in ``Path.rglob()`` and ``re`` module, so it works
    on all platforms without external ``grep``.

    Args:
        pattern: Regex pattern.
        include: File glob filter (e.g. ``*.py``).
        root: Root directory.

    Returns:
        Matching lines with file prefixes, or a "not found" message.
    """
    import fnmatch  # noqa: PLC0415
    import os  # noqa: PLC0415

    root_path = Path(root)
    if not root_path.is_dir():
        return f"Error: not a directory: {root}"

    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"Error: invalid regex pattern '{pattern}': {exc}"

    matches: list[str] = []
    total = 0
    for filepath in root_path.rglob("*"):
        if not filepath.is_file():
            continue
        if not fnmatch.fnmatch(filepath.name, include):
            continue
        try:
            text = filepath.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                rel = os.path.relpath(filepath, root)
                matches.append(f"{rel}:{lineno}:{line}")
                total += 1
                if total >= 500:
                    break
        if total >= 500:
            matches.append("... (truncated at 500 matches)")
            break

    if not matches:
        return f"No matches for '{pattern}' in {root}"

    output = "\n".join(matches)
    if total >= 500:
        return f"{output}\n{total} lines matched (truncated)"
    return f"{output}\n{total} lines matched"
