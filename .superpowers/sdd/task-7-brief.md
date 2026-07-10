# Task Brief: Task 7 - Provider Transport Abstraction

## Context

AgentsX providers currently implement `stream()` and `format_messages()` directly in each provider class. This mixes format conversion with client construction, streaming, credential refresh, and retry logic. hermes-agent separates these into a clean Transport ABC that owns ONLY format conversion.

## What This Task Does

Create a `ProviderTransport` ABC with `format_messages()`, `build_kwargs()`, and `parse_stream()` methods. Implement `OpenAITransport` and `AnthropicTransport` concrete classes. The existing providers compose their transport.

## Files to Create

1. `agentsx/provider/transport.py` — ProviderTransport ABC + concrete implementations
2. `tests/test_transport.py` — Tests

## Exact Implementation

### transport.py

```python
class ProviderTransport(ABC):
    @abstractmethod
    def format_messages(self, messages: list[AgentMessage]) -> list[dict[str, Any]]: ...

    @abstractmethod
    def build_kwargs(self, *, messages: list[dict[str, Any]],
                     tools: list[dict[str, Any]] | None = None,
                     max_tokens: int = 4096, **extra: Any) -> dict[str, Any]: ...

    @abstractmethod
    async def parse_stream(self, response: Any) -> AsyncIterator[StreamEvent]: ...
```

### OpenAITransport

- `format_messages()` — delegates to `msg._to_openai()` for each message
- `build_kwargs()` — builds OpenAI API kwargs (model, messages, max_tokens, stream, tools)
- `parse_stream()` — iterates OpenAI streaming response, yields `TextStreamEvent` for content deltas and `ToolCallStreamEvent` for completed tool calls

### AnthropicTransport

- `format_messages()` — separates system message, delegates to `msg._to_anthropic()` for others
- `build_kwargs()` — builds Anthropic API kwargs (model, messages, max_tokens, system, tools)
- `parse_stream()` — iterates Anthropic streaming response, yields `TextStreamEvent` for text deltas

### Tests

```python
def test_openai_transport_format_messages() -> None:
    transport = OpenAITransport()
    messages = [AgentMessage(role=MessageRole.SYSTEM, content="You are helpful"),
                AgentMessage(role=MessageRole.USER, content="Hello")]
    result = transport.format_messages(messages)
    assert len(result) == 2
    assert result[0]["role"] == "system"

def test_openai_transport_with_tool_calls() -> None:
    transport = OpenAITransport()
    msg = AgentMessage(role=MessageRole.ASSISTANT, content="",
                       tool_calls=[ToolCall(id="tc_1", name="read", arguments={"path": "x.txt"})])
    result = transport.format_messages([msg])
    assert "tool_calls" in result[0]
    assert result[0]["tool_calls"][0]["function"]["name"] == "read"

def test_anthropic_transport_format_messages() -> None:
    transport = AnthropicTransport()
    messages = [AgentMessage(role=MessageRole.SYSTEM, content="You are helpful"),
                AgentMessage(role=MessageRole.USER, content="Hello")]
    result = transport.format_messages(messages)
    assert len(result) >= 1

def test_transport_build_kwargs_openai() -> None:
    transport = OpenAITransport()
    kwargs = transport.build_kwargs(messages=[{"role": "user", "content": "hi"}],
                                    tools=[], max_tokens=100)
    assert "messages" in kwargs
    assert "max_tokens" in kwargs
```

## Important Constraints

- Google-style docstrings only
- Full type annotations required
- `Any` is acceptable ONLY in transport method signatures where it's unavoidable (response types from external libraries)
- Line length max 88 characters, `git add <file-path>` only
- Note: `parse_stream()` implementations work with raw API responses — the `Any` type for response parameter is unavoidable and acceptable

## Validation Required Before Commit

```bash
uv run ruff check agentsx/ tests/
uv run ruff format --check agentsx/ tests/
uv run mypy agentsx/ tests/ --strict
uv run pytest tests/test_transport.py -v
uv run pytest -v  # full suite
```

## Report

Write detailed report to `d:/An/CODE/AgentsX/.superpowers/sdd/task-7-report.md`.
Return status as one of: DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, BLOCKED.
