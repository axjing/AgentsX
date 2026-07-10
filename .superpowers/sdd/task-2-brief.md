# Task Brief: Task 2 - Structured Tool Results

## Context

AgentsX is an AI agent runtime framework. Currently, tool execution returns plain strings — the loop receives `(result_text, is_error)` tuples and wraps them in a basic `ToolResult` dataclass. This makes it impossible for UIs or downstream systems to access metadata like truncation status, execution duration, or structured error details.

## What This Task Does

Reference tau's `AgentToolResult` pattern. Replace the plain-string tool result with a structured `ToolResult` dataclass containing status enum, content, error detail, and optional metadata dictionary. `ToolSpec.call()` returns `ToolResult` instead of `str`. The loop consumes the structured result.

## Files to Create

1. `agentsx/core/tool_result.py` — Structured ToolResult dataclass
2. `tests/test_tool_result.py` — Tests

## Files to Modify

1. `agentsx/core/types.py` — Remove old ToolResult dataclass (lines 197-204), add re-export from tool_result module
2. `agentsx/tools/__init__.py` — Change `ToolSpec.call()` return type from `str` to `ToolResult`
3. `agentsx/agent/loop.py` — Update `_execute_tool_with_status()` to work with structured ToolResult from ToolSpec.call()

## Exact Implementation

### tool_result.py

- `ToolResultStatus(str, Enum)` — values: SUCCESS, ERROR, BLOCKED
- `ToolResult(dataclass)` — fields: tool_call_id (str), status (ToolResultStatus), content (str), error (Exception | None = None), metadata (dict[str, str] = field(default_factory=dict))
- Properties: `is_success`, `is_error`, `is_blocked`, `error_detail`
- Method: `to_legacy_string()` — backward compat, returns content for success, error_detail for error/blocked
- Method: `__repr__()` — truncated content at 60 chars

### ToolSpec.call() Change

Change return type from `str` to `ToolResult`:
- On success: `ToolResult(tool_call_id="", status=ToolResultStatus.SUCCESS, content=str(result))`
- On error: `ToolResult(tool_call_id="", status=ToolResultStatus.ERROR, content=str(exc), error=exc)`

### loop.py Changes

`_execute_tool_with_status()` now receives ToolResult from `tools.call()`, applies truncation, and returns a new ToolResult with the proper `tool_call_id`. The main loop no longer wraps results in `ToolResult()` — it receives them directly.

## Important Constraints

- Use `(str, Enum)` mixin for ToolResultStatus
- Google-style docstrings only
- Full type annotations required
- `snake_case` for functions/variables, `PascalCase` for classes
- No bare `except:`, no mutable defaults
- Line length max 88 characters
- Tests use `pytest-asyncio` with `asyncio_mode = "auto"`
- `git add <file-path>` only — no `git add .` or `git add -A`

## Validation Required Before Commit

```bash
uv run ruff check agentsx/ tests/
uv run ruff format --check agentsx/ tests/
uv run mypy agentsx/ tests/ --strict
uv run pytest tests/test_tool_result.py -v
```

## Report

Write a detailed report to:
`d:/An/CODE/AgentsX/.superpowers/sdd/task-2-report.md`

Include: test results, files changed, self-review findings, concerns.

Return status as one of: DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, BLOCKED
