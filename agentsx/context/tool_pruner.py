"""Tool output pre-pruning for context compaction.

Before sending tool outputs to an LLM for summarization, this module
replaces verbose outputs with concise one-line summaries.  This reduces
token consumption and improves summary quality.

Inspired by Hermes-Agent's ``_summarize_tool_result()`` pattern.
"""

import json
import re
from collections.abc import Callable

from agentsx.protocol.messages import AgentMessage, MessageRole, ToolCall


def _extract_tool_call_info(msg: AgentMessage) -> list[tuple[str, str, str]]:
    """Extract (tool_call_id, tool_name, arguments_json) from a message."""
    if not msg.tool_calls:
        return []
    result: list[tuple[str, str, str]] = []
    for tc in msg.tool_calls:
        args_str = json.dumps(tc.arguments, ensure_ascii=False) if tc.arguments else ""
        result.append((tc.id, tc.name, args_str))
    return result


def _summarize_bash(args: dict[str, object], content: str) -> str:
    """Summarize a terminal/bash tool call."""
    cmd = str(args.get("command", ""))
    if len(cmd) > 80:
        cmd = cmd[:77] + "..."
    exit_match = re.search(r'"exit_code"\s*:\s*(-?\d+)', content)
    exit_code = exit_match.group(1) if exit_match else "?"
    lines = content.count("\n") + 1 if content.strip() else 0
    return f"[terminal] ran `{cmd}` -> exit {exit_code}, {lines} lines output"


def _summarize_read(args: dict[str, object], content: str) -> str:
    """Summarize a file read tool call."""
    path = str(args.get("path", "?"))
    content_len = len(content)
    return f"[read] {path} ({content_len:,} chars)"


def _summarize_write(args: dict[str, object], content: str) -> str:
    """Summarize a file write tool call."""
    path = str(args.get("path", "?"))
    written = content.count("\n") + 1 if content.strip() else 0
    return f"[write] {path} ({written} lines)"


def _summarize_edit(args: dict[str, object], content: str) -> str:
    """Summarize a file edit tool call."""
    path = str(args.get("path", "?"))
    content_len = len(content)
    return f"[edit] {path} ({content_len:,} chars result)"


def _summarize_grep(args: dict[str, object], content: str) -> str:
    """Summarize a grep/search tool call."""
    pattern = str(args.get("pattern", "?"))
    path = str(args.get("path", "."))
    match_count = re.search(r'"total_count"\s*:\s*(\d+)', content)
    count = match_count.group(1) if match_count else "?"
    return f"[grep] '{pattern}' in {path} -> {count} matches"


def _summarize_glob(args: dict[str, object], content: str) -> str:
    """Summarize a glob tool call."""
    pattern = str(args.get("pattern", "?"))
    content_len = len(content)
    return f"[glob] '{pattern}' ({content_len:,} chars)"


def _summarize_web_fetch(args: dict[str, object], content: str) -> str:
    """Summarize a web fetch tool call."""
    url = str(args.get("url", "?"))
    content_len = len(content)
    return f"[web_fetch] {url} ({content_len:,} chars)"


def _summarize_web_search(args: dict[str, object], content: str) -> str:
    """Summarize a web search tool call."""
    query = str(args.get("query", "?"))
    content_len = len(content)
    return f"[web_search] '{query}' ({content_len:,} chars)"


# Tool name -> summarizer function mapping.
_SUMMARIZERS: dict[str, Callable[[dict[str, object], str], str]] = {
    "tool_bash": _summarize_bash,
    "tool_file_read": _summarize_read,
    "tool_file_write": _summarize_write,
    "tool_file_edit": _summarize_edit,
    "tool_file_grep": _summarize_grep,
    "tool_file_glob": _summarize_glob,
    "tool_web_fetch": _summarize_web_fetch,
    "tool_web_search": _summarize_web_search,
}

# Maximum content length to keep verbatim (chars).
_VERBATIM_THRESHOLD = 2000


def summarize_tool_call(tool_name: str, args: dict[str, object], content: str) -> str:
    """Create a concise one-line summary of a tool call and its result.

    Uses tool-specific summarizers when available, falls back to a
    generic format.

    Args:
        tool_name: Name of the tool (e.g. ``"tool_bash"``).
        args: Tool call arguments dict.
        content: Tool result content string.

    Returns:
        A one-line summary string.
    """
    summarizer = _SUMMARIZERS.get(tool_name)
    if summarizer:
        try:
            return summarizer(args, content)
        except Exception:  # noqa: BLE001
            pass

    # Generic fallback
    first_args = ""
    for k, v in list(args.items())[:2]:
        sv = str(v)[:40]
        first_args += f" {k}={sv}"
    return f"[{tool_name}]({first_args.strip()}) ({len(content):,} chars)"


def prune_tool_output(content: str, threshold: int = _VERBATIM_THRESHOLD) -> str:
    """Prune a tool output to a manageable size.

    If content is under *threshold*, returns it unchanged.
    Otherwise, keeps head and tail with a truncation marker.

    Args:
        content: The tool output content.
        threshold: Maximum chars to keep verbatim.

    Returns:
        Pruned content string.
    """
    if len(content) <= threshold:
        return content

    keep_head = min(1000, threshold // 3)
    keep_tail = min(500, threshold // 3)
    omitted = len(content) - keep_head - keep_tail
    return (
        content[:keep_head]
        + f"\n\n... [{omitted:,} chars omitted] ...\n\n"
        + content[-keep_tail:]
    )


def prune_messages_for_compaction(
    messages: list[AgentMessage],
    preserve_count: int = 12,
) -> list[AgentMessage]:
    """Prune tool outputs in older messages before compaction.

    Messages in the preserved tail are left unchanged.  Older messages
    get their tool results replaced with concise summaries.

    Args:
        messages: Full conversation history.
        preserve_count: Number of recent messages to preserve verbatim.

    Returns:
        New message list with pruned tool outputs.
    """
    if len(messages) <= preserve_count:
        return messages

    # Build tool_call_id -> (tool_name, args) lookup from assistant messages
    tc_info: dict[str, tuple[str, dict[str, object]]] = {}
    for msg in messages:
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tc_info[tc.id] = (tc.name, tc.arguments or {})

    result: list[AgentMessage] = []
    for i, msg in enumerate(messages):
        # Preserve tail messages verbatim
        if i >= len(messages) - preserve_count:
            result.append(msg)
            continue

        # Prune tool result messages
        if msg.role == MessageRole.TOOL and msg.tool_call_id:
            info = tc_info.get(msg.tool_call_id)
            if info:
                tool_name, args = info
                summary = summarize_tool_call(tool_name, args, msg.content)
                result.append(
                    AgentMessage(
                        role=msg.role,
                        content=summary,
                        tool_call_id=msg.tool_call_id,
                    )
                )
                continue

        # For assistant messages with tool_calls, keep the calls but note pruning
        if msg.tool_calls:
            pruned_calls = []
            for tc in msg.tool_calls:
                pruned_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.name,
                        arguments=tc.arguments,
                    )
                )
            result.append(
                AgentMessage(
                    role=msg.role,
                    content=msg.content,
                    tool_calls=pruned_calls,
                )
            )
            continue

        result.append(msg)

    return result
