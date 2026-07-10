# Task Brief: Task 1 - Centralized Error Classifier

## Context

You are working on the AgentsX project, an AI agent runtime framework with ReAct loop, multi-provider support, and security layers. This task is part of a progressive optimization initiative inspired by two 3rdparty projects (tau and hermes-agent).

## What This Task Does

Create a centralized error classification system inspired by hermes-agent's priority-ordered error classification pipeline. All API errors get mapped to a structured `ClassifiedError` with `FailoverReason` enum and `RecoveryAction` dataclass, replacing scattered try/except and string matching across the codebase.

## Files to Create

1. `agentsx/core/error_classifier.py` — The classification module
2. `tests/test_error_classifier.py` — Tests

## Files to Modify

1. `agentsx/agent/loop.py` — Integrate classifier into error handling

## Exact Implementation

### error_classifier.py

Create this file with the complete implementation. Key types:

- `FailoverReason(str, Enum)` — values: THINKING_SIGNATURE, CONTEXT_OVERFLOW, BILLING_EXHAUSTED, AUTH_ERROR, RATE_LIMIT, SERVER_ERROR, NETWORK_ERROR, UNKNOWN
- `RecoveryAction(dataclass)` — fields: should_retry (bool), should_compress (bool), should_fallback (bool), delay_seconds (float), user_hint (str)
- `ClassifiedError(dataclass)` — fields: reason (FailoverReason), recovery (RecoveryAction), original (ProviderError), message (str)
- `classify_api_error(err: ProviderError) -> ClassifiedError` — main entry point

Classification priority (highest first):
1. Thinking signature mismatch — check message + cause for "thinking" AND ("signature" OR "not allowed")
2. Context overflow — check for markers: "context length", "maximum context", "token limit", "too many tokens", "prompt is too long", "input length"
3. HTTP status code: 401 → auth (not retryable), 402 → billing (unless contains "try again" or "temporary" → rate limit), 429 → rate limit, 403 → auth, 5xx → server error
4. Network heuristics — check for "connection", "timeout", "network", "ssl", "tls", "disconnect", "refused", "reset"
5. Fallback → UNKNOWN but retryable

### Tests

Write 8 test functions as specified in the plan (lines 71-157 of the plan file).

### loop.py Integration

In `run_agent_loop()`, replace the `except Exception as exc:` block (around lines 214-229) to:
1. Classify the error using `classify_api_error()`
2. If `should_compress` is True and `compact` is enabled, attempt auto-compaction and `continue` to retry
3. Otherwise yield `ErrorEvent` with classified context

## Important Constraints

- Use `(str, Enum)` mixin for FailoverReason (Python 3.10 compat)
- Google-style docstrings only
- `snake_case` for functions/variables, `PascalCase` for classes
- No bare `except:` — always catch explicit types
- Full type annotations on all parameters and return values
- Line length max 88 characters
- Tests use `pytest-asyncio` with `asyncio_mode = "auto"` (already configured in pyproject.toml)
- `git add <file-path>` only — no `git add .` or `git add -A`

## Validation Required Before Commit

```bash
uv run ruff check agentsx/ tests/
uv run ruff format --check agentsx/ tests/
uv run mypy agentsx/ tests/ --strict
uv run pytest tests/test_error_classifier.py -v
```

## Report

After implementation, write a detailed report to:
`d:/An/CODE/AgentsX/.superpowers/sdd/task-1-report.md`

Include: test results (pass/fail counts), files changed, self-review findings, concerns.

Return status as one of: DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, BLOCKED
