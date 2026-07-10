# Task 5 Report: Append-only Session Compaction

**Status: DONE**

## Summary

Implemented an append-only compaction entry system that records compaction
operations without modifying the session message file. This preserves a
full audit trail of all compaction events.

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `agentsx/context/compaction_entry.py` | Created | `CompactionEntry` dataclass, `replay_messages()`, `load_compaction_entries()`, `append_compaction_entry()` |
| `agentsx/session/store.py` | Modified | Added `append_compaction_entry()` method; added `_List` alias to work around `.list()` shadowing |
| `tests/test_compaction_entry.py` | Created | 4 test functions covering serialization, deserialization, replay without/with compaction |

## Implementation Details

### CompactionEntry

A `@dataclass` with three fields:
- `replaces_ids: list[str]` -- message IDs replaced by this compaction
- `summary: str` -- human-readable summary text
- `token_estimate: int = 0` -- estimated tokens saved

Provides `to_dict()` and `from_dict()` for JSON serialization.

### replay_messages()

Algorithm:
1. Builds a set of all replaced message IDs from all compaction entries
2. Iterates messages in order
3. Skips messages whose IDs are in the replaced set
4. At the first consecutive replaced message, creates a summary `AgentMessage`
   with role=ASSISTANT and the compaction entry's summary
5. Returns the resulting filtered message list

### load_compaction_entries() / append_compaction_entry()

Free-function helpers that operate on a JSONL file path. `load` returns an
empty list when the file does not exist. `append` creates parent directories
if needed.

### SessionStore.append_compaction_entry()

Convenience method on `SessionStore` that creates a `CompactionEntry` and
appends it to `<session_dir>/compaction.jsonl`. Validates session existence
and raises `SessionError` if not found.

## Validation Results

| Check | Result |
|-------|--------|
| `ruff check` (target files) | PASS |
| `ruff format --check` (target files) | PASS |
| `mypy --strict` (full codebase) | PASS (0 issues) |
| `pytest tests/test_compaction_entry.py` | 4/4 passed |
| `pytest` (full suite) | 247/247 passed |

## Commit

- `f6b5d5d` feat(session): add append-only compaction entry system

## Concerns

None.
