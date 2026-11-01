"""Filesystem write and edit tools."""

import difflib
from pathlib import Path

from agentsx.tools import tool


@tool(description="Write content to a file (overwrite or create).", toolset="write")
def tool_file_write(path: str, content: str) -> str:
    """Write content to a file (overwrite or create).

    Args:
        path: Path to the target file.
        content: The text content to write.

    Returns:
        Confirmation message with byte count.
    """
    filepath = Path(path)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    written = filepath.write_text(content, encoding="utf-8")
    return f"Wrote {written} bytes to {path}"


@tool(
    description="Edit an existing file by performing an exact-text replacement.",
    toolset="write",
)
def tool_file_edit(
    path: str,
    old_string: str,
    new_string: str,
) -> str:
    """Edit an existing file by performing an exact-text replacement.

    Generates and returns a unified diff hunk of the applied change.

    Args:
        path: Path to the file to edit.
        old_string: Exact substring to replace.
        new_string: Drop-in replacement string.

    Returns:
        Success message with unified diff hunk, or error message.
    """
    filepath = Path(path)
    if not filepath.exists():
        return f"Error: file not found: {path}"
    if not filepath.is_file():
        return f"Error: not a file: {path}"

    text = filepath.read_text(encoding="utf-8", errors="replace")
    is_crlf = "\r\n" in text

    target_old = old_string
    target_new = new_string

    if target_old not in text:
        norm_text = text.replace("\r\n", "\n")
        norm_old = old_string.replace("\r\n", "\n")
        if norm_old in norm_text:
            if is_crlf:
                target_old = norm_old.replace("\n", "\r\n")
                target_new = new_string.replace("\r\n", "\n").replace("\n", "\r\n")
            else:
                target_old = norm_old
                target_new = new_string.replace("\r\n", "\n")
        else:
            return f"Error: old_string not found in {path}"

    if target_old == target_new:
        return f"No changes made to {path}: old_string and new_string are identical."

    match_count = text.count(target_old)
    if match_count > 1:
        return (
            f"Error: old_string matches {match_count} locations in {path}. "
            "Please include more surrounding context to make replacement unique."
        )

    new_text = text.replace(target_old, target_new, 1)
    filepath.write_text(new_text, encoding="utf-8")

    diff_lines = list(
        difflib.unified_diff(
            text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=3,
        )
    )
    diff_str = "".join(diff_lines).strip()
    return f"Edited {path} successfully:\n\n```diff\n{diff_str}\n```"
