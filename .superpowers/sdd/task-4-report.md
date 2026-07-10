# Task 4 Report: AgentHarness Facade

## Status

DONE

## Summary

Created `AgentHarness` -- a stateful facade that wraps `run_agent_loop()` with subscriber management, cancellation, and queue injection (follow-up + steering).

## Files Changed

| File | Lines | Purpose |
|------|-------|---------|
| `agentsx/agent/harness.py` | 194 | New module with `AgentHarness` class and `EventListener` type alias |
| `tests/test_harness.py` | 130 | 6 test functions covering the full public API |

## Design Decisions

### Architecture

`AgentHarness` sits at a higher altitude than the existing `Agent` class. It:

- **Owns state**: message history (`_messages`), cancellation flag (`_cancelled`), event listeners (`_listeners`), follow-up queue (`_follow_up_queue`), and steering queue (`_steer_queue`).
- **Delegates execution**: `_run_loop()` calls the pure `run_agent_loop()` generator, dispatching each yielded event to registered subscribers before re-yielding it.
- **Drains queues**: After the main loop completes, `prompt()` drains the follow-up queue by appending each queued message as a new user turn and re-running the loop.

### Type Alias

```python
EventListener = Callable[[AgentEvent], None]
```

Defined at module level per requirements. Consumers pass a callable that receives each `AgentEvent` during prompt execution.

### Queue Patterns

- **Follow-up queue** (`deque[str]`): Messages queued before `prompt()` is called. Drained sequentially after the main loop exits.
- **Steering queue** (`deque[str]`): Passed directly to `run_agent_loop()` which already supports `steer_queue` for interrupt-and-redirect mid-loop.

### Cancellation

The `cancel()` method sets `_cancelled = True`. The `prompt()` method checks this flag before draining follow-up messages, so cancellation prevents further queued turns from executing. The current loop step completes naturally (as designed -- no mid-step interruption).

### Listener Error Handling

Listener exceptions are caught and silently swallowed (no `except:` bare clause -- uses `except Exception:` per project convention). This ensures one broken listener never crashes the prompt execution or affects other listeners.

### Google-style Docstrings

All public methods and the class itself have Google-style docstrings with proper `Args:` and `Returns:` sections.

## Validation Results

| Check | Result |
|-------|--------|
| `ruff check` | All passed |
| `ruff format --check` | 2 files already formatted |
| `mypy --strict` | Success: no issues found in 83 source files |
| `pytest tests/test_harness.py` | 6/6 passed |
| `pytest` (full suite) | 243/243 passed, 1 pre-existing warning |

## Tests

| Test | What It Verifies |
|------|-----------------|
| `test_harness_prompt_yields_events` | `prompt()` yields `AgentStartEvent` and `AgentEndEvent` |
| `test_harness_remembers_history` | Multiple `prompt()` calls share and accumulate message history |
| `test_harness_subscribe_event_listener` | Subscribed listener receives events during prompt; unsubscribe works |
| `test_harness_cancel` | Cancelled harness yields initial events but skips follow-up queue |
| `test_harness_follow_up_queue` | Queued follow-up messages trigger additional turns |
| `test_harness_clear_history` | History cleared but system prompt preserved; queues cleared too |

## Commit

```
ead93df feat(agent): add AgentHarness facade with subscriber, cancel, and queue support
```

## Concerns

None. The implementation follows the brief exactly, all validation passes, and the full test suite (243 tests) remains green.
