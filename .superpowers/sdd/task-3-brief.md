# Task Brief: Task 3 - Expanded Event Stream

## Context

AgentsX is an AI agent runtime framework. Currently, `agentsx/core/types.py` defines only 6 event types: `ModelRequestEvent`, `ModelResponseEvent`, `ToolExecutionEvent`, `ErrorEvent`, `CompactionEvent`, `PromptEvent`. This is insufficient for consumers to render precise UI states (agent start/end, turn boundaries, individual text deltas, tool execution start, retries).

## What This Task Does

Reference tau's complete event stream pattern. Expand from 6 to 13 event types, covering the full agent lifecycle. The `AgentEvent` union type is updated accordingly. The `run_agent_loop()` in `loop.py` is updated to yield these new events at appropriate points.

## Files to Modify

1. `agentsx/core/types.py` — Add 7 new event dataclasses, update `AgentEvent` union
2. `agentsx/agent/loop.py` — Yield new events at start/end/turn/tool/retry points
3. `tests/test_events.py` — Tests for new event types

## Exact Implementation

### New Event Types (add to types.py in the Events section, before the AgentEvent union)

```python
@dataclass
class AgentStartEvent:
    """Emitted when the agent loop begins."""
    model: str
    step: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

@dataclass
class AgentEndEvent:
    """Emitted when the agent loop completes."""
    step: int
    reason: str
    """``"completed"`` (no tool calls), ``"max_steps"``, or ``"error"``."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

@dataclass
class TurnStartEvent:
    """Emitted at the start of each agent turn."""
    turn: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

@dataclass
class TurnEndEvent:
    """Emitted at the end of each agent turn."""
    turn: int
    had_tool_calls: bool
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

@dataclass
class TextDeltaEvent:
    """A single text token from the model response."""
    text: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

@dataclass
class RetryEvent:
    """Emitted when a provider retry/backoff occurs."""
    attempt: int
    max_attempts: int
    reason: str
    delay: float
    """Seconds until next retry."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

@dataclass
class ToolExecutionStartEvent:
    """Emitted before a tool call is executed."""
    tool_name: str
    tool_call_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

### Updated AgentEvent Union

Replace the existing `AgentEvent = ...` union with:
```python
AgentEvent = (
    AgentStartEvent | AgentEndEvent | TurnStartEvent | TurnEndEvent
    | ModelRequestEvent | TextDeltaEvent | ModelResponseEvent
    | ToolExecutionStartEvent | ToolExecutionEvent
    | ErrorEvent | CompactionEvent | PromptEvent | RetryEvent
)
```

### loop.py Changes

In `run_agent_loop()`:

1. **Before the `while step < max_steps` loop**: yield `AgentStartEvent(model=provider.model.id, step=0)`

2. **After `step += 1`**: yield `TurnStartEvent(turn=step)`

3. **In the provider stream loop** — for each `TextStreamEvent`, also yield a `TextDeltaEvent`:
```python
if isinstance(event, TextStreamEvent):
    content_parts.append(event.text)
    yield TextDeltaEvent(text=event.text)  # NEW
    # ... existing code ...
```

4. **Before `break` (no tools → loop is done)**: yield `TurnEndEvent(turn=step, had_tool_calls=False)`

5. **Before each tool execution in the `for tc_event in pending_calls` loop**: yield `ToolExecutionStartEvent(tool_name=tc.name, tool_call_id=tc.id)`

6. **After all tool executions** (at the end of the while loop body, before steer queue processing): yield `TurnEndEvent(turn=step, had_tool_calls=True)`

7. **After the while loop** (normal completion): yield `AgentEndEvent(step=step, reason="completed" if step < max_steps else "max_steps")`

## Tests

Write tests in `tests/test_events.py`:

```python
# 1 test per new event type construction
def test_agent_start_event() -> None:
    event = AgentStartEvent(model="gpt-4o", step=1)
    assert event.model == "gpt-4o"
    assert event.step == 1
    assert isinstance(event.timestamp, datetime)

def test_agent_end_event() -> None:
    event = AgentEndEvent(step=3, reason="completed")
    assert event.step == 3
    assert event.reason == "completed"

def test_turn_start_event() -> None:
    event = TurnStartEvent(turn=2)
    assert event.turn == 2

def test_turn_end_event_no_tools() -> None:
    event = TurnEndEvent(turn=1, had_tool_calls=False)
    assert event.had_tool_calls is False

def test_text_delta_event() -> None:
    event = TextDeltaEvent(text="Hello")
    assert event.text == "Hello"

def test_retry_event() -> None:
    event = RetryEvent(attempt=2, max_attempts=3, reason="rate limit", delay=5.0)
    assert event.attempt == 2
    assert event.delay == 5.0

def test_tool_execution_start_event() -> None:
    event = ToolExecutionStartEvent(tool_name="file_read", tool_call_id="tc_001")
    assert event.tool_name == "file_read"

# Union dispatch test
def test_agent_event_union_dispatch() -> None:
    events: list[AgentEvent] = [
        AgentStartEvent(model="gpt-4o", step=1),
        AgentEndEvent(step=1, reason="completed"),
        TurnStartEvent(turn=1),
        TurnEndEvent(turn=1, had_tool_calls=True),
        TextDeltaEvent(text="hi"),
        RetryEvent(attempt=1, max_attempts=3, reason="timeout", delay=5.0),
        ToolExecutionStartEvent(tool_name="bash", tool_call_id="x"),
    ]
    for event in events:
        assert isinstance(event, AgentEvent)
```

## Important Constraints

- Use existing imports from `datetime`, `dataclass` — already in types.py
- Google-style docstrings only
- Full type annotations required
- `snake_case` for functions/variables, `PascalCase` for classes
- Line length max 88 characters
- `git add <file-path>` only — no `git add .` or `git add -A`
- Tests use `pytest-asyncio` with `asyncio_mode = "auto"` (already configured)

## Validation Required Before Commit

```bash
uv run ruff check agentsx/ tests/
uv run ruff format --check agentsx/ tests/
uv run mypy agentsx/ tests/ --strict
uv run pytest tests/test_events.py -v
uv run pytest -v  # full suite — must pass with no regressions
```

## Report

Write a detailed report to:
`d:/An/CODE/AgentsX/.superpowers/sdd/task-3-report.md`

Include: test results (pass/fail counts), files changed, self-review findings, concerns.

Return status as one of: DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, BLOCKED
