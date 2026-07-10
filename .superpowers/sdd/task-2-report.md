# Task 2 Report: Structured Tool Results

**Status:** DONE

## Summary

Replaced plain-string tool results (`tuple[str, bool]`) with a structured `ToolResult` dataclass that carries a status enum (`ToolResultStatus.SUCCESS | ERROR | BLOCKED`), content string, optional exception object, and metadata dictionary. `ToolSpec.call()` and `ToolRegistry.call()` now return `ToolResult` instead of `str`. The agent loop consumes the structured result directly.

## Commits Made

- **4c7ebcb** — `feat: replace plain-string tool results with structured ToolResult`
  - Created `agentsx/core/tool_result.py` with `ToolResultStatus(str, Enum)` and `ToolResult` dataclass
  - Removed old `@dataclass ToolResult` from `agentsx/core/types.py`, added re-export
  - Updated `ToolSpec.call()` in `agentsx/tools/__init__.py` to return `ToolResult`
  - Updated `ToolRegistry.call()` to return `ToolResult` (unknown tool returns error result instead of raising)
  - Updated `agentsx/agent/loop.py` `_execute_tool_with_status()` to return `ToolResult` directly
  - FORBIDDEN/PROMPT policy decisions now produce `ToolResultStatus.BLOCKED` results
  - Updated all existing tests to use new constructor signature and `.content` accessor
  - 6 new tests in `tests/test_tool_result.py`

## Files Changed

| File | Change |
|------|--------|
| `agentsx/core/tool_result.py` | **New** — ToolResultStatus enum, ToolResult dataclass |
| `agentsx/core/types.py` | Remove old ToolResult dataclass, add re-export |
| `agentsx/tools/__init__.py` | `ToolSpec.call()` and `ToolRegistry.call()` return ToolResult |
| `agentsx/agent/loop.py` | `_execute_tool_with_status()` returns ToolResult; loop constructs ToolResult for policy blocks |
| `tests/test_tool_result.py` | **New** — 6 test functions |
| `tests/test_types.py` | Updated ToolResult constructor usage to new signature |
| `tests/test_tools.py` | Updated call() assertions, unknown tool test, decorator test |
| `tests/test_extensions.py` | Mock returns ToolResult instead of plain string |
| `tests/test_security.py` | Renamed test to reflect BLOCKED status (not ERROR) |

## Test Results

```
uv run ruff check agentsx/ tests/        → All checks passed!
uv run ruff format --check agentsx/ tests/ → 83 files already formatted
uv run mypy agentsx/ tests/ --strict     → Success: no issues found in 80 source files
uv run pytest tests/ --ignore=tests/test_agent.py -v → 221 passed, 1 warning
```

The 1 warning is a pre-existing unawaited coroutine in `test_error_event_on_stream_failure`, unrelated to this change.

## Self-Review Findings

1. **ToolResultStatus uses `(str, Enum)` mixin** as required, making it compatible with Python 3.10+ and string-comparable (`.value` equals the string literal).
2. **`ToolRegistry.call()` no longer raises on unknown tool** — it returns an error `ToolResult` instead. This is a behavioral change but aligns with the structured result pattern (errors are data, not exceptions).
3. **`_execute_tool_with_status()` no longer has a try/except** — errors are already captured in the `ToolResult` from `ToolSpec.call()`. The function only applies truncation to successful results.
4. **`to_legacy_string()`** provides backward compatibility for any downstream code that still expects a string (e.g., message content, extension event content).
5. **FORBIDDEN/PROMPT policy decisions** now produce `ToolResultStatus.BLOCKED` results in the loop, which is semantically more accurate than `is_error=True`.

## Concerns / Open Questions

1. **`error` field typed as `Exception | None`** — mypy strict passes, but the `Exception` type is broad. Downstream consumers that inspect `result.error` should use `isinstance()` checks for specificity.
2. **`metadata` typed as `dict[str, str]`** — the plan specified this constraint. If downstream systems need richer values (ints, bools), this should be widened to `dict[str, Any]`.
3. **No `id` field on `ToolResult`** — the old dataclass had both `id` and `tool_call_id`. The new design uses only `tool_call_id` (the correlation ID). The old `id` field (`f"tr_{tc.id}"`) was not referenced anywhere in the codebase.
4. **`__all__` in `types.py`** — added to satisfy mypy's `attr-defined` check for the re-export. This means `from agentsx.core.types import ToolResult, ToolResultStatus` remains valid.
