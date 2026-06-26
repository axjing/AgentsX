"""Context window compaction for long conversations.

Inspired by Pi's branch-summarization approach: when the message list
exceeds a threshold, older messages are compacted into a summary message
while preserving recent messages and all tool call/results.

Design:
    - Simple token-count based compaction (no LLM call needed)
    - Preserves: system message + last N messages + all tool calls
    - Compacted older messages become a single summary placeholder
"""

from __future__ import annotations

from agentsx.core.types import AgentMessage, MessageRole

# Average characters per token (rough estimate for most models)
_CHARS_PER_TOKEN = 4

# Minimum messages to always preserve (system + recent conversation)
_MIN_PRESERVE = 12


def estimate_tokens(text: str) -> int:
    """Estimate token count from character length."""
    return len(text) // _CHARS_PER_TOKEN


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


def compact_messages(
    messages: list[AgentMessage],
    preserve_count: int = _MIN_PRESERVE,
) -> list[AgentMessage]:
    """Compact older messages into a summary placeholder.

    Preserves:
        - First system message (always)
        - Last *preserve_count* messages (most recent)
        - All tool call/results within preserved range

    Compacted older messages are replaced with a single summary
    placeholder that notes how many messages were compacted.

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
    compacted_count = len(working) - len(preserved)

    if compacted_count <= 0:
        if system_msg:
            return [system_msg] + working
        return working

    # Calculate token count of compacted portion
    compacted_tokens = sum(
        estimate_message_tokens(m) for m in working[:-preserve_count]
    )

    # Create summary placeholder
    summary = AgentMessage(
        role=MessageRole.SYSTEM,
        content=(
            f"[{compacted_count} earlier messages compacted "
            f"(~{compacted_tokens} tokens omitted)]"
        ),
    )

    result: list[AgentMessage] = []
    if system_msg:
        result.append(system_msg)
    result.append(summary)
    result.extend(preserved)

    return result
