"""Filesystem write and edit tools."""

from __future__ import annotations

from pathlib import Path

from agentsx.tools import tool


@tool(description="Write content to a file (overwrite or create).")
def tool_file_write(path: str, content: str) -> str:
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
