"""Append-only compaction entries for session audit trail.

CompactionEntry records are written to ``compaction.jsonl`` alongside
the session's ``messages.jsonl``.  During replay, referenced messages
are replaced with their summary, preserving an append-only audit record.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentsx.core.types import AgentMessage, MessageRole


@dataclass
class CompactionEntry:
    """Records a compaction without modifying the session file."""

    replaces_ids: list[str]
    summary: str
    token_estimate: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-serialisable dict."""
        return {
            "type": "compaction",
            "replaces_ids": self.replaces_ids,
            "summary": self.summary,
            "token_estimate": self.token_estimate,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CompactionEntry":
        """Deserialize from a parsed JSON dict."""
        return cls(
            replaces_ids=data.get("replaces_ids", []),
            summary=data.get("summary", ""),
            token_estimate=data.get("token_estimate", 0),
        )


def replay_messages(
    messages: list[AgentMessage],
    compaction_entries: list[CompactionEntry],
) -> list[AgentMessage]:
    """Replay messages with compaction awareness.

    Referenced message IDs are replaced with summary messages at the
    position of the first message in each consecutive replaced group.

    Args:
        messages: The full message list from the session.
        compaction_entries: Compaction records for this session.

    Returns:
        A new message list with compacted ranges summarised.
    """
    # Build a set of all replaced message IDs
    replaced_ids: set[str] = set()
    for entry in compaction_entries:
        replaced_ids.update(entry.replaces_ids)

    # Build a lookup from message ID to its compaction entry (if any)
    id_to_entry: dict[str, CompactionEntry] = {}
    for entry in compaction_entries:
        for mid in entry.replaces_ids:
            id_to_entry[mid] = entry

    result: list[AgentMessage] = []
    i = 0
    while i < len(messages):
        msg = messages[i]

        if msg.id not in replaced_ids:
            # Not replaced — keep as-is
            result.append(msg)
            i += 1
            continue

        # This message is replaced. Collect the consecutive group.
        entry = id_to_entry[msg.id]
        # Create a summary message at the position of the first replaced
        summary_msg = AgentMessage(
            role=MessageRole.ASSISTANT,
            content=entry.summary,
            id=f"compaction-{msg.id[:8]}",
        )
        result.append(summary_msg)

        # Skip all consecutive messages that are in this entry's set
        entry_ids = set(entry.replaces_ids)
        while i < len(messages) and messages[i].id in entry_ids:
            i += 1

    return result


def load_compaction_entries(path: Path) -> list[CompactionEntry]:
    """Load compaction entries from a JSONL file.

    Args:
        path: Path to the ``compaction.jsonl`` file.

    Returns:
        A list of CompactionEntry objects, in file order.
    """
    entries: list[CompactionEntry] = []
    if not path.is_file():
        return entries
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                data = json.loads(stripped)
                entries.append(CompactionEntry.from_dict(data))
    return entries


def append_compaction_entry(
    path: Path,
    entry: CompactionEntry,
) -> None:
    """Append a compaction entry to the JSONL file.

    Args:
        path: Path to the ``compaction.jsonl`` file.
        entry: The CompactionEntry to append.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry.to_dict(), separators=(",", ":"))
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
