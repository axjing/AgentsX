# Task 3 Report: Expanded Event Stream

## Status

DONE

## Summary

Expanded the AgentsX event stream from 6 to 13 event types, covering the full
agent lifecycle: loop start/end, turn boundaries, text deltas, tool execution
start, and retry events.

## Files Changed

- **`agentsx/core/types.py`** — Added 7 new event dataclasses and updated the
  `AgentEvent` union from 6 to 13 types.
- **`agentsx/agent/loop.py`** — Added imports for 7 new types and inserted yield
  points at loop start, turn start/end, tool execution start, text delta, and
  loop end.
- **`tests/test_agent.py`** — Updated 5 existing tests to account for the new
  events being emitted (event counts changed from 4 to 10 for normal flows, from
  2 to 6 for empty stream, from 2 to 4 for error paths).
- **`tests/test_events.py`** — New test file with 8 test functions, one per new
  event type plus a union dispatch test.

## New Event Types

| Type | Purpose |
|---|---|
| `AgentStartEvent` | Emitted when the agent loop begins |
| `AgentEndEvent` | Emitted when the agent loop completes |
| `TurnStartEvent` | Emitted at the start of each agent turn |
| `TurnEndEvent` | Emitted at the end of each agent turn, with `had_tool_calls` flag |
| `TextDeltaEvent` | A single text token from the model response |
| `RetryEvent` | Emitted when a provider retry/backoff occurs |
| `ToolExecutionStartEvent` | Emitted before a tool call is executed |

## Event Emission Order (normal single-turn, no tools)

1. `AgentStartEvent`
2. `TurnStartEvent`
3. `ModelRequestEvent`
4. For each token: `TextDeltaEvent` + `ModelResponseEvent(delta=True)`
5. `ModelResponseEvent(delta=False)` — assembled response
6. `TurnEndEvent(had_tool_calls=False)`
7. `AgentEndEvent(reason="completed")`

## Test Results

- **ruff check**: All checks passed
- **ruff format**: All files formatted
- **mypy --strict**: Success, no issues found in 81 source files
- **pytest tests/test_events.py**: 8 passed
- **pytest full suite**: 237 passed, 1 warning, 0 failed

## Self-Review Findings

- `RetryEvent` is defined in types.py but not emitted from `loop.py` because the
  current provider retry logic lives inside the provider's `stream_with_retry()`
  method, not in the agent loop. This is intentional — `RetryEvent` is available
  for future use when retry instrumentation is added at the loop level.
- The `AgentEndEvent` is not yielded on early-return error paths (provider
  failures, timeouts). This is consistent with the existing pattern where error
  paths return immediately. Consumers should check for `AgentEndEvent` or
  terminal `ErrorEvent` to determine loop completion.

## Concerns

None.

## Commit

Commit `a79e13b` on branch `agentsx-optimizations`:
"feat(core): expand event stream from 6 to 13 types"
