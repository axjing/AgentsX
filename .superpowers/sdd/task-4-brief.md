# Task Brief: Task 4 - AgentHarness Facade

## Context

AgentsX is an AI agent runtime framework. Currently, `agentsx/agent/agent.py` provides a simple `Agent` class that wraps `run_agent_loop()`, but it mixes state management (messages, provider resolution) with loop execution. There is no support for event subscribers, cancellation, or message queue injection.

## What This Task Does

Reference tau's `AgentHarness` pattern. Create a stateful facade that owns the transcript (message history), cancellation, event listeners, and prompt queues (steering + follow-up). The harness delegates execution to the pure `run_agent_loop()` async generator.

## Files to Create

1. `agentsx/agent/harness.py` — AgentHarness class
2. `tests/test_harness.py` — Tests

## Exact Implementation

### AgentHarness Class

```python
class AgentHarness:
    def __init__(
        self,
        provider: Provider,
        system_prompt: str | None = None,
        tools: ToolRegistry | None = None,
        policy: ExecutionPolicy | None = None,
        extensions: ExtensionAPI | None = None,
        max_steps: int | None = None,
    ) -> None:
        # Owns messages, listeners, cancelled flag, follow-up queue, steer queue
        # Appends system prompt message if provided

    @property
    def provider(self) -> Provider: ...
    @property
    def messages(self) -> list[AgentMessage]: ...  # read-only copy

    async def prompt(self, user_input: str, *, timeout: float = 0) -> AsyncIterator[AgentEvent]:
        # Append user message, run loop, dispatch to subscribers
        # After loop drains, drain follow-up queue as additional turns

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        # Register listener, return unsubscribe callback

    def queue_follow_up(self, content: str) -> None:
        # Queue message for after current turn completes

    def queue_steering(self, content: str) -> None:
        # Queue message for mid-run injection (next turn)

    def cancel(self) -> None:
        # Set cancelled flag — current run finishes after current step

    def clear_history(self) -> None:
        # Clear messages, keep system prompt, clear queues
```

### Tests

```python
class _FakeProvider:
    """Minimal provider for testing."""
    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = responses or ["OK"]
        self.call_count = 0
        self.model = type("Model", (), {"id": "fake-model"})()
        self.tools = None

    async def stream_with_retry(self, messages):
        self.call_count += 1
        resp = self.responses[self.call_count - 1] if self.call_count <= len(self.responses) else "done"
        yield ModelResponseEvent(content=resp, delta=False)

@pytest.mark.asyncio
async def test_harness_prompt_yields_events() -> None:
    harness = AgentHarness(provider=_FakeProvider(["Hello back"]))
    events = []
    async for event in harness.prompt("Hi"):
        events.append(event)
    types = {type(e).__name__ for e in events}
    assert "AgentStartEvent" in types
    assert "AgentEndEvent" in types

@pytest.mark.asyncio
async def test_harness_remembers_history() -> None:
    harness = AgentHarness(provider=_FakeProvider(["A", "B"]))
    await harness.prompt("First").__anext__()
    await harness.prompt("Second").__anext__()
    assert len(harness.messages) >= 3

@pytest.mark.asyncio
async def test_harness_subscribe_event_listener() -> None:
    received: list[str] = []
    harness = AgentHarness(provider=_FakeProvider(["echo"]))
    def on_event(event) -> None:
        received.append(type(event).__name__)
    unsub = harness.subscribe(on_event)
    async for _ in harness.prompt("test"):
        pass
    assert len(received) > 0
    unsub()

@pytest.mark.asyncio
async def test_harness_cancel() -> None:
    harness = AgentHarness(provider=_FakeProvider(["slow"]))
    harness.cancel()
    events = []
    async for event in harness.prompt("test"):
        events.append(event)
    assert len(events) > 0

@pytest.mark.asyncio
async def test_harness_follow_up_queue() -> None:
    harness = AgentHarness(provider=_FakeProvider(["step1", "step2"]))
    harness.queue_follow_up("also do this")
    events = []
    async for event in harness.prompt("do that"):
        events.append(event)
    assert len(events) > 0

@pytest.mark.asyncio
async def test_harness_clear_history() -> None:
    harness = AgentHarness(provider=_FakeProvider(["a"]), system_prompt="You are helpful")
    await harness.prompt("Hi").__anext__()
    harness.clear_history()
    assert len(harness.messages) == 1
    assert harness.messages[0].role == MessageRole.SYSTEM
```

## Important Constraints

- Use `(str, Enum)` mixin if any enums needed
- Google-style docstrings only
- Full type annotations required
- `EventListener = Callable[[AgentEvent], None]` as module-level type alias
- No bare `except:`, no mutable defaults
- Line length max 88 characters
- `git add <file-path>` only
- Tests use `pytest-asyncio` with `asyncio_mode = "auto"`

## Validation Required Before Commit

```bash
uv run ruff check agentsx/ tests/
uv run ruff format --check agentsx/ tests/
uv run mypy agentsx/ tests/ --strict
uv run pytest tests/test_harness.py -v
uv run pytest -v  # full suite
```

## Report

Write detailed report to:
`d:/An/CODE/AgentsX/.superpowers/sdd/task-4-report.md`

Return status as one of: DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, BLOCKED
