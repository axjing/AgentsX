# Task Brief: Task 5 - Append-only Session Compaction

## Context

AgentsX stores sessions as JSONL files under `~/.agentsx/sessions/<id>/messages.jsonl`. Currently, compaction replaces messages in memory with no persistent record. This task adds an append-only compaction entry system.

## What This Task Does

Create `CompactionEntry` dataclass appended to `compaction.jsonl`. Replay replaces referenced messages with summaries, preserving audit history.

## Files to Create

1. `agentsx/context/compaction_entry.py`
2. `tests/test_compaction_entry.py`

## Files to Modify

1. `agentsx/session/store.py` — Add `append_compaction_entry()` method

## Exact Implementation

### compaction_entry.py

```python
@dataclass
class CompactionEntry:
    """Records a compaction without modifying the session file."""
    replaces_ids: list[str]
    summary: str
    token_estimate: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"type": "compaction", "replaces_ids": self.replaces_ids,
                "summary": self.summary, "token_estimate": self.token_estimate}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CompactionEntry:
        return cls(replaces_ids=data.get("replaces_ids", []),
                   summary=data.get("summary", ""),
                   token_estimate=data.get("token_estimate", 0))

def replay_messages(messages: list[AgentMessage], compaction_entries: list[CompactionEntry]) -> list[AgentMessage]:
    """Replay messages with compaction awareness. Referenced message IDs are replaced with summary messages."""

def load_compaction_entries(path: Path) -> list[CompactionEntry]:
    """Load compaction entries from a JSONL file."""

def append_compaction_entry(path: Path, entry: CompactionEntry) -> None:
    """Append a compaction entry to the JSONL file."""
```

### SessionStore Modification

```python
def append_compaction_entry(self, session_id: str, replaces_ids: list[str],
                            summary: str, token_estimate: int = 0) -> None:
    """Record a compaction without modifying the session file."""
```

### Tests

4 test functions as specified:
1. `test_compaction_entry_serialization`
2. `test_compaction_entry_deserialization`
3. `test_replay_without_compaction`
4. `test_replay_with_compaction`

## Important Constraints

- `from typing import Any` is acceptable in this file for serialization helpers
- Google-style docstrings only
- Full type annotations required
- Line length max 88 characters
- `git add <file-path>` only

## Validation Required Before Commit

```bash
uv run ruff check agentsx/ tests/
uv run ruff format --check agentsx/ tests/
uv run mypy agentsx/ tests/ --strict
uv run pytest tests/test_compaction_entry.py -v
uv run pytest -v  # full suite
```

## Report

Write detailed report to `d:/An/CODE/AgentsX/.superpowers/sdd/task-5-report.md`.
Return status as one of: DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, BLOCKED.
