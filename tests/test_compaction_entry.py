"""Tests for append-only compaction entry system."""

from agentsx.context.compaction_entry import (
    CompactionEntry,
    replay_messages,
)
from agentsx.core.types import AgentMessage, MessageRole


def test_compaction_entry_serialization() -> None:
    """CompactionEntry serialises to a dict with the expected keys."""
    entry = CompactionEntry(
        replaces_ids=["id-1", "id-2", "id-3"],
        summary="Summarised 3 messages",
        token_estimate=150,
    )
    result = entry.to_dict()
    assert result["type"] == "compaction"
    assert result["replaces_ids"] == ["id-1", "id-2", "id-3"]
    assert result["summary"] == "Summarised 3 messages"
    assert result["token_estimate"] == 150


def test_compaction_entry_deserialization() -> None:
    """CompactionEntry can be reconstructed from a dict."""
    data = {
        "type": "compaction",
        "replaces_ids": ["a", "b"],
        "summary": "Two messages merged",
        "token_estimate": 80,
    }
    entry = CompactionEntry.from_dict(data)
    assert entry.replaces_ids == ["a", "b"]
    assert entry.summary == "Two messages merged"
    assert entry.token_estimate == 80

    # Defaults when keys are missing
    minimal = CompactionEntry.from_dict({})
    assert minimal.replaces_ids == []
    assert minimal.summary == ""
    assert minimal.token_estimate == 0


def test_replay_without_compaction() -> None:
    """When no compaction entries exist, replay returns all messages."""
    messages = [
        AgentMessage(role=MessageRole.SYSTEM, content="Be helpful.", id="msg-0"),
        AgentMessage(role=MessageRole.USER, content="Hi", id="msg-1"),
        AgentMessage(role=MessageRole.ASSISTANT, content="Hello!", id="msg-2"),
    ]
    result = replay_messages(messages, [])
    assert len(result) == 3
    assert result == messages


def test_replay_with_compaction() -> None:
    """Compacted messages are replaced with a summary message."""
    messages = [
        AgentMessage(role=MessageRole.SYSTEM, content="Be helpful.", id="msg-0"),
        AgentMessage(role=MessageRole.USER, content="msg 1", id="msg-1"),
        AgentMessage(role=MessageRole.ASSISTANT, content="resp 1", id="msg-2"),
        AgentMessage(role=MessageRole.USER, content="msg 2", id="msg-3"),
        AgentMessage(role=MessageRole.ASSISTANT, content="resp 2", id="msg-4"),
    ]
    entry = CompactionEntry(
        replaces_ids=["msg-1", "msg-2"],
        summary="Early conversation summarised",
    )
    result = replay_messages(messages, [entry])
    # System + summary + msg-3 + msg-4
    assert len(result) == 4
    assert result[0].id == "msg-0"
    assert result[0].content == "Be helpful."
    assert "Early conversation summarised" in result[1].content
    assert result[2].id == "msg-3"
    assert result[3].id == "msg-4"
