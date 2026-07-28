"""Context window compaction for long conversations.

Inspired by Pi's branch-summarization and Hermes-Agent's context_compressor.

Design:
    - Unicode-aware token estimation (CJK vs Latin vs whitespace)
    - Tool output pre-pruning (reduces token waste before summarization)
    - Structured summary template (completed tasks, in-progress, decisions)
    - Iterative summary updates (preserves info across multiple compactions)
    - Token-budget tail protection (keeps recent messages verbatim)
    - Summary end marker (prevents model from reading summary as input)
    - Summary is a USER-role message for provider compatibility
"""

import unicodedata

from agentsx.context.tool_pruner import prune_messages_for_compaction
from agentsx.protocol.messages import AgentMessage, MessageRole

# Base estimate: ~4 characters per token for Latin/whitespace text.
_LATIN_CHARS_PER_TOKEN = 4

# CJK characters typically consume 1-2 tokens each (closer to 1 token).
_CJK_CHARS_PER_TOKEN = 1.5

# Minimum messages to always preserve (system + recent conversation)
_MIN_PRESERVE = 12

# Summary end marker — tells the model the summary is context, not instructions.
_SUMMARY_END_MARKER = (
    "--- END OF CONTEXT SUMMARY — "
    "respond to the message below, not the summary above ---"
)

# Structured summary template for LLM-generated summaries.
_STRUCTURED_SUMMARY_TEMPLATE = """[CONTEXT COMPACTION — REFERENCE ONLY]
Earlier turns were compacted into the summary below. This is a handoff
from a previous context window — treat it as background reference, NOT
as active instructions. Respond ONLY to the latest user message that
appears AFTER this summary.

## Completed Tasks
{completed}

## In Progress
{in_progress}

## Key Decisions
{decisions}

## Relevant Files
{files}
"""


def estimate_tokens(text: str) -> int:
    """Estimate token count with Unicode-aware character categorization.

    CJK characters (Chinese, Japanese, Korean) typically tokenize to
    1-2 tokens each, while Latin prose averages ~4 chars per token.
    Whitespace characters are counted at a reduced rate (~8 chars/token).
    """
    cjk = 0
    latin = 0
    ws = 0
    for ch in text:
        cat = unicodedata.category(ch)
        if cat.startswith("C"):  # control/format, treat as whitespace-like
            ws += 1
        elif cat.startswith("L") and ch > "\x7f":
            # Letter outside ASCII -> likely CJK or other non-Latin
            if (
                "\u4e00" <= ch <= "\u9fff"
                or "\u3400" <= ch <= "\u4dbf"
                or "\u3040" <= ch <= "\u309f"  # hiragana
                or "\u30a0" <= ch <= "\u30ff"  # katakana
                or "\uac00" <= ch <= "\ud7af"  # hangul syllables
            ):
                cjk += 1
            else:
                latin += 1
        else:
            latin += 1

    cjk_tokens = max(1, int(cjk / _CJK_CHARS_PER_TOKEN)) if cjk else 0
    latin_tokens = max(1, int(latin / _LATIN_CHARS_PER_TOKEN)) if latin else 0
    ws_tokens = int(ws / (_LATIN_CHARS_PER_TOKEN * 2))
    return cjk_tokens + latin_tokens + ws_tokens


def estimate_message_tokens(msg: AgentMessage) -> int:
    """Estimate token count for a single message."""
    tokens = estimate_tokens(msg.content)
    if msg.tool_calls:
        tokens += len(msg.tool_calls) * 10
    return tokens


def should_compact(
    messages: list[AgentMessage],
    max_tokens: int = 0,
    max_messages: int = 50,
) -> bool:
    """Check if messages exceed compaction thresholds.

    Args:
        messages: Current conversation messages.
        max_tokens: Maximum total token budget (0 = disabled).
        max_messages: Maximum message count before compaction.

    Returns:
        True if compaction should be triggered.
    """
    if len(messages) < _MIN_PRESERVE + 2:
        return False

    if len(messages) >= max_messages > 0:
        return True

    if max_tokens > 0:
        total = sum(estimate_message_tokens(m) for m in messages)
        if total >= max_tokens:
            return True

    return False


def _summarize_tool_calls(
    messages: list[AgentMessage],
) -> list[str]:
    """Extract a summary of tool calls and results from messages.

    Returns a list of human-readable lines like::

        tool_call: read(path='/etc/hosts')
        result for tc_abc: ConnectionError: timed out...
    """
    lines: list[str] = []
    for msg in messages:
        if msg.tool_calls:
            for tc in msg.tool_calls:
                args = ", ".join(f"{k}={v!r}" for k, v in tc.arguments.items())
                lines.append(f"tool_call: {tc.name}({args})")
        elif msg.role == MessageRole.TOOL and msg.tool_call_id:
            preview = msg.content[:200]
            ellipsis = "..." if len(msg.content) > 200 else ""
            lines.append(f"result for {msg.tool_call_id}: {preview}{ellipsis}")
    return lines


def _extract_structured_info(
    messages: list[AgentMessage],
) -> dict[str, list[str]]:
    """Extract structured information from messages for the summary template.

    Returns a dict with keys: completed, in_progress, decisions, files.
    Each value is a list of bullet-point strings.
    """
    completed: list[str] = []
    in_progress: list[str] = []
    decisions: list[str] = []
    files: list[str] = []

    for msg in messages:
        if msg.role != MessageRole.ASSISTANT:
            continue

        content = msg.content.strip()
        if not content:
            continue

        # Extract tool calls as completed actions
        if msg.tool_calls:
            for tc in msg.tool_calls:
                action = f"`{tc.name}`"
                if tc.arguments:
                    path = tc.arguments.get("path", "")
                    if path:
                        action += f" on `{path}`"
                        if path not in files:
                            files.append(path)
                completed.append(action)

        # Extract assistant text as potential decisions/in-progress
        # Use simple heuristics: short sentences -> decisions, longer -> in-progress
        sentences = [s.strip() for s in content.split(".") if s.strip()]
        for sentence in sentences[:3]:
            if len(sentence) < 80:
                decisions.append(sentence)
            else:
                in_progress.append(sentence[:100] + "...")

    return {
        "completed": completed[:10],
        "in_progress": in_progress[:5],
        "decisions": decisions[:5],
        "files": files[:10],
    }


def _build_structured_summary(
    messages: list[AgentMessage],
    existing_summary: str | None = None,
) -> str:
    """Build a structured summary from messages.

    If *existing_summary* is provided, merges new info with the old summary
    (iterative compaction).
    """
    info = _extract_structured_info(messages)

    # Format bullet points
    def format_bullets(items: list[str]) -> str:
        if not items:
            return "- (none)"
        return "\n".join(f"- {item}" for item in items)

    summary = _STRUCTURED_SUMMARY_TEMPLATE.format(
        completed=format_bullets(info["completed"]),
        in_progress=format_bullets(info["in_progress"]),
        decisions=format_bullets(info["decisions"]),
        files=format_bullets(info["files"]),
    )

    # Merge with existing summary if present
    if existing_summary:
        # Extract the old summary's sections (best-effort)
        summary = (
            f"{summary}\n\n"
            f"Previous summary (also reference-only):\n"
            f"{existing_summary}"
        )

    return summary


def _find_existing_summary(messages: list[AgentMessage]) -> str | None:
    """Find an existing compaction summary in the message list.

    Returns the summary content if found, None otherwise.
    """
    for msg in messages:
        if (
            msg.role == MessageRole.USER
            and "[CONTEXT COMPACTION" in msg.content
        ):
            return msg.content
    return None


def compact_messages(
    messages: list[AgentMessage],
    preserve_count: int = _MIN_PRESERVE,
) -> list[AgentMessage]:
    """Compact older messages into a structured summary placeholder.

    Preserves:
        - First system message (always)
        - Last *preserve_count* messages (most recent)

    Compacted older messages are replaced with a structured summary
    that includes completed tasks, in-progress work, key decisions,
    and relevant files.

    The summary ends with a marker to prevent the model from
    interpreting it as active instructions.

    Args:
        messages: Current conversation messages.
        preserve_count: Number of recent messages to preserve.

    Returns:
        New message list with older messages compacted.
    """
    if len(messages) <= _MIN_PRESERVE + 1:
        return messages

    # Always preserve the system message
    system_msg = None
    working = list(messages)
    if working[0].role == MessageRole.SYSTEM:
        system_msg = working.pop(0)

    # Keep the last N messages
    preserved = working[-preserve_count:]
    compacted = working[:-preserve_count]
    compacted_count = len(compacted)

    if compacted_count <= 0:
        if system_msg:
            return [system_msg] + working
        return working

    # Check for existing summary to merge (iterative compaction)
    existing_summary = _find_existing_summary(compacted)

    # Build structured summary
    summary_text = _build_structured_summary(compacted, existing_summary)

    # Add end marker
    summary_text += f"\n\n{_SUMMARY_END_MARKER}"

    # Calculate token count of compacted portion
    compacted_tokens = sum(estimate_message_tokens(m) for m in compacted)

    # Prepend token info
    summary_content = (
        f"[{compacted_count} earlier messages compacted "
        f"(~{compacted_tokens} tokens omitted)]\n\n"
        f"{summary_text}"
    )

    summary = AgentMessage(
        role=MessageRole.USER,
        content=summary_content,
    )

    result: list[AgentMessage] = []
    if system_msg:
        result.append(system_msg)
    result.append(summary)
    result.extend(preserved)

    return result


def compact_messages_with_pruning(
    messages: list[AgentMessage],
    preserve_count: int = _MIN_PRESERVE,
) -> list[AgentMessage]:
    """Compact with tool output pre-pruning before summary generation.

    This is the recommended entry point for compaction.  It first prunes
    verbose tool outputs in older messages, then applies structured
    compaction.

    Args:
        messages: Full conversation history.
        preserve_count: Number of recent messages to preserve.

    Returns:
        Compacted message list with pruned tool outputs.
    """
    # Phase 1: Prune tool outputs in older messages
    pruned = prune_messages_for_compaction(messages, preserve_count=preserve_count)

    # Phase 2: Apply structured compaction
    return compact_messages(pruned, preserve_count=preserve_count)
