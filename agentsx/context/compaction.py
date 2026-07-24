"""Context window compaction for long conversations.

Inspired by Pi's branch-summarization approach: when the message list
exceeds a threshold, older messages are compacted into a summary message
while preserving recent messages and tool call summaries.

Design:
    - Unicode-aware token estimation (CJK vs Latin vs whitespace)
    - Preserves: system message + last N messages
    - Compacted tool calls/results are summarized in the summary placeholder
      so the LLM can reference what was done without the full payload
    - Summary is a USER-role message to stay provider-compatible
      (Anthropic requires user as first message, single system only)
"""

import unicodedata

from agentsx.protocol.messages import AgentMessage, MessageRole

# Base estimate: ~4 characters per token for Latin/whitespace text.
_LATIN_CHARS_PER_TOKEN = 4

# CJK characters typically consume 1-2 tokens each (closer to 1 token).
_CJK_CHARS_PER_TOKEN = 1.5

# Minimum messages to always preserve (system + recent conversation)
_MIN_PRESERVE = 12


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
        elif cat.startswith("L") and ch > "":
            # Letter outside ASCII → likely CJK or other non-Latin
            if (
                "一" <= ch <= "鿿"
                or "㐀" <= ch <= "䶿"
                or "぀" <= ch <= "ゟ"  # hiragana
                or "゠" <= ch <= "ヿ"  # katakana
                or "가" <= ch <= "힯"  # hangul syllables
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


def compact_messages(
    messages: list[AgentMessage],
    preserve_count: int = _MIN_PRESERVE,
) -> list[AgentMessage]:
    """Compact older messages into a summary placeholder.

    Preserves:
        - First system message (always)
        - Last *preserve_count* messages (most recent)
        - Tool call history within preserved range

    Compacted older messages are replaced with a summary placeholder
    that includes:
        - How many messages were compacted
        - Token count omitted
        - Summaries of all tool calls and their results
          (so the LLM can reference what was done without the full payload)

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

    # Calculate token count of compacted portion
    compacted_tokens = sum(estimate_message_tokens(m) for m in compacted)

    # Build tool call summary for compacted region
    tool_summary_lines = _summarize_tool_calls(compacted)

    # Create summary placeholder
    content_parts = [
        f"[{compacted_count} earlier messages compacted "
        f"(~{compacted_tokens} tokens omitted)]",
    ]
    if tool_summary_lines:
        content_parts.append("")
        content_parts.append("Tool calls in compacted history:")
        content_parts.extend(f"  - {line}" for line in tool_summary_lines)

    summary = AgentMessage(
        role=MessageRole.USER,
        content="\n".join(content_parts),
    )

    result: list[AgentMessage] = []
    if system_msg:
        result.append(system_msg)
    result.append(summary)
    result.extend(preserved)

    return result
