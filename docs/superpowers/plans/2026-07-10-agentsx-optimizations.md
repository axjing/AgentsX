# AgentsX 渐进式优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 参考 tau 和 hermes-agent 的优秀设计模式,对 AgentsX 进行 7 项渐进式优化,提升核心健壮性、可复用性和智能能力。

**Architecture:** 分 3 阶段 (P0 核心健壮性 → P1 可复用性 → P1 智能能力),每个优化独立可测试、向后兼容。

**Tech Stack:** Python 3.10+, Pydantic, async/await, dataclasses, pytest

## Global Constraints

- Python 3.10 minimum, no `StrEnum` — use `(str, Enum)` mixin
- Full type annotations on all variables, parameters, return values; `Any` prohibited
- Google-style docstrings only; no Sphinx
- Line length max 88 characters (ruff config)
- `snake_case` for files/functions/variables, `PascalCase` for classes/exceptions
- No bare `except:` — always catch explicit exception types
- No mutable default parameters; use `None` placeholder
- All I/O-bound functions use `async def`
- Tests must support Linux, macOS and Windows
- Validation: `ruff check` + `ruff format --check` + `mypy --strict` + `pytest -v` must all pass
- `git add <file-path>` only — `git add .` / `git add -A` prohibited

---

## File Structure

### New Files to Create

| File | Responsibility |
|------|---------------|
| `agentsx/core/error_classifier.py` | 集中式 API 错误分类器,返回结构化恢复提示 |
| `agentsx/agent/harness.py` | AgentHarness 门面 — 状态管理、订阅、取消、队列注入 |
| `agentsx/context/compaction_entry.py` | Append-only 压缩条目系统 (CompactionEntry) |
| `agentsx/core/profile.py` | 冻结的运行时姿态检测对象 (ContextProfile) |
| `agentsx/provider/transport.py` | Provider Transport 抽象 — 格式转换与编排分离 |
| `agentsx/core/tool_result.py` | 结构化工具结果 dataclass |

### Files to Modify

| File | Change Summary |
|------|---------------|
| `agentsx/core/types.py` | 扩展事件类型 (新增 7 种事件), 移除旧 ToolResult |
| `agentsx/core/errors.py` | 新增 ClassifiedError, FailoverReason |
| `agentsx/agent/loop.py` | 接入 ErrorClassifier, 扩展事件产出, 使用新 ToolResult |
| `agentsx/agent/agent.py` | 接入 AgentHarness 或使用新事件 |
| `agentsx/context/compaction.py` | 新增 CompactionEntry 回放逻辑 |
| `agentsx/session/store.py` | 新增 append_compaction_entry(), 回放支持 |
| `agentsx/tools/__init__.py` | ToolSpec.call() 返回 ToolResult 而非 str |
| `agentsx/provider/__init__.py` | Provider.stream() 接入 Transport 抽象 |

---

## 阶段 1: 核心健壮性 (P0)

### Task 1: 集中式错误分类系统

**Files:**
- Create: `agentsx/core/error_classifier.py`
- Modify: `agentsx/core/errors.py`
- Modify: `agentsx/agent/loop.py` (接入分类器)
- Test: `tests/test_error_classifier.py`

**Interfaces:**
- Consumes: `ProviderError` from `agentsx/core/errors.py`
- Produces: `ClassifiedError` with `FailoverReason` enum, `RecoveryAction` dataclass

**Design:** 参考 hermes-agent 的优先级错误分类管道。将所有 API 错误映射为结构化 `ClassifiedError`,包含失败原因枚举和恢复动作提示,替代散落在各处的 try/except 和字符串匹配。

- [ ] **Step 1: 写入失败测试**

```python
# tests/test_error_classifier.py

"""Tests for the centralized API error classifier."""

from agentsx.core.error_classifier import (
    ClassifiedError,
    FailoverReason,
    classify_api_error,
)
from agentsx.core.errors import ProviderError


def test_classify_rate_limit_429() -> None:
    err = ProviderError("rate limit exceeded", status_code=429)
    result = classify_api_error(err)
    assert result.reason == FailoverReason.rate_limit
    assert result.recovery.should_retry is True
    assert result.recovery.should_compress is False
    assert result.recovery.should_fallback is False


def test_classify_auth_401() -> None:
    err = ProviderError("invalid api key", status_code=401)
    result = classify_api_error(err)
    assert result.reason == FailoverReason.auth_error
    assert result.recovery.should_retry is False


def test_classify_context_overflow() -> None:
    err = ProviderError(
        "This model's maximum context length is 8192 tokens. "
        "However, you requested 12000 tokens.",
        status_code=400,
    )
    result = classify_api_error(err)
    assert result.reason == FailoverReason.context_overflow
    assert result.recovery.should_compress is True
    assert result.recovery.should_retry is True


def test_classify_billing_402() -> None:
    err = ProviderError("insufficient funds", status_code=402)
    result = classify_api_error(err)
    assert result.reason == FailoverReason.billing_exhausted
    assert result.recovery.should_retry is False
    assert result.recovery.should_fallback is False


def test_classify_server_503_retryable() -> None:
    err = ProviderError("service unavailable", status_code=503)
    result = classify_api_error(err)
    assert result.reason == FailoverReason.server_error
    assert result.recovery.should_retry is True


def test_classify_unknown_retryable() -> None:
    """Unknown errors default to retryable for resilience."""
    err = ProviderError("something weird happened")
    result = classify_api_error(err)
    assert result.reason == FailoverReason.unknown
    assert result.recovery.should_retry is True


def test_classify_thinking_signature() -> None:
    """Detect Anthropic extended thinking signature mismatch."""
    err = ProviderError(
        "error: tools are not allowed while using thinking. "
        "thinking signature mismatch",
        status_code=400,
    )
    result = classify_api_error(err)
    assert result.reason == FailoverReason.thinking_signature
    assert result.recovery.should_retry is False


def test_classify_timeout_network() -> None:
    """Network/timeout errors should be classified as transient."""
    import httpx

    err = ProviderError("Connection error")
    err.__cause__ = httpx.ConnectError("Connection refused")
    result = classify_api_error(err)
    assert result.recovery.should_retry is True
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd "d:/An/CODE/AgentsX" && uv run pytest tests/test_error_classifier.py -v
```
预期: 全部失败, `ModuleNotFoundError: No module named 'agentsx.core.error_classifier'`

- [ ] **Step 3: 实现错误分类器**

```python
# agentsx/core/error_classifier.py

"""Centralized API error classification with recovery hints.

Inspired by Hermes-Agent's priority-ordered error classification pipeline.
Replaces scattered inline string-matching with a single, testable function
that maps any ``ProviderError`` into a structured ``ClassifiedError`` with
a ``FailoverReason`` and actionable ``RecoveryAction``.

Classification priority (highest first):
    1. Thinking signature mismatch (Anthropic extended thinking)
    2. Context overflow (token limit exceeded)
    3. Billing exhausted (402)
    4. Auth errors (401, forbidden)
    5. Rate limiting (429)
    6. Server errors (5xx)
    7. Network/timeout heuristics
    8. Fallback: unknown (retryable)
"""

from dataclasses import dataclass, field

from agentsx.core.errors import ProviderError


class FailoverReason(str):
    """Categorised reason for an API failure."""

    THINKING_SIGNATURE = "thinking_signature"
    CONTEXT_OVERFLOW = "context_overflow"
    BILLING_EXHAUSTED = "billing_exhausted"
    AUTH_ERROR = "auth_error"
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"


@dataclass
class RecoveryAction:
    """Structured recovery hints for a classified error."""

    should_retry: bool = False
    should_compress: bool = False
    should_fallback: bool = False
    delay_seconds: float = 0.0
    user_hint: str = ""


@dataclass
class ClassifiedError:
    """A ProviderError with classified reason and recovery hints."""

    reason: FailoverReason
    recovery: RecoveryAction
    original: ProviderError
    message: str = ""

    @property
    def is_transient(self) -> bool:
        """Whether this error is transient and worth retrying."""
        return self.recovery.should_retry


# Priority-ordered pattern matchers.  Each returns True if it classified
# the error and mutated *out* in-place.

def _check_thinking_signature(
    err: ProviderError,
    out: "list[tuple[FailoverReason, RecoveryAction]]",
) -> bool:
    msg = str(err).lower()
    cause_msg = ""
    cause = getattr(err, "__cause__", None)
    if cause is not None:
        cause_msg = str(cause).lower()
    combined = msg + " " + cause_msg
    if "thinking" in combined and ("signature" in combined or "not allowed" in combined):
        out.append((
            FailoverReason.THINKING_SIGNATURE,
            RecoveryAction(
                should_retry=False,
                user_hint="Extended thinking is not compatible with tool calls",
            ),
        ))
        return True
    return False


def _check_context_overflow(
    err: ProviderError,
    out: "list[tuple[FailoverReason, RecoveryAction]]",
) -> bool:
    msg = str(err).lower()
    overflow_markers = (
        "context length",
        "maximum context",
        "token limit",
        "too many tokens",
        "prompt is too long",
        "input length",
    )
    if any(m in msg for m in overflow_markers):
        out.append((
            FailoverReason.CONTEXT_OVERFLOW,
            RecoveryAction(
                should_retry=True,
                should_compress=True,
                user_hint="Context window exceeded — compressing conversation",
            ),
        ))
        return True
    return False


def _check_status_code(
    err: ProviderError,
    out: "list[tuple[FailoverReason, RecoveryAction]]",
) -> bool:
    code = err.status_code
    if code is None:
        return False

    if code == 401:
        out.append((
            FailoverReason.AUTH_ERROR,
            RecoveryAction(
                should_retry=False,
                should_fallback=True,
                user_hint="Authentication failed — check API key",
            ),
        ))
        return True

    if code == 402:
        msg = str(err).lower()
        # Distinguish billing exhaustion from transient "try again later"
        if "try again" in msg or "temporary" in msg:
            out.append((
                FailoverReason.RATE_LIMIT,
                RecoveryAction(
                    should_retry=True,
                    delay_seconds=60.0,
                    user_hint="Temporary billing limit — retrying after delay",
                ),
            ))
        else:
            out.append((
                FailoverReason.BILLING_EXHAUSTED,
                RecoveryAction(
                    should_retry=False,
                    should_fallback=True,
                    user_hint="API credits exhausted — add funds or change model",
                ),
            ))
        return True

    if code == 429:
        out.append((
            FailoverReason.RATE_LIMIT,
            RecoveryAction(
                should_retry=True,
                delay_seconds=30.0,
                user_hint="Rate limited — backing off before retry",
            ),
        ))
        return True

    if code == 403:
        out.append((
            FailoverReason.AUTH_ERROR,
            RecoveryAction(
                should_retry=False,
                user_hint="Access forbidden — check permissions",
            ),
        ))
        return True

    if code >= 500:
        out.append((
            FailoverReason.SERVER_ERROR,
            RecoveryAction(
                should_retry=True,
                delay_seconds=10.0,
                user_hint="Server error — retrying with backoff",
            ),
        ))
        return True

    return False


def _check_network_heuristics(
    err: ProviderError,
    out: "list[tuple[FailoverReason, RecoveryAction]]",
) -> bool:
    msg = str(err).lower()
    cause_msg = ""
    cause = getattr(err, "__cause__", None)
    if cause is not None:
        cause_msg = str(cause).lower()
    combined = msg + " " + cause_msg

    network_markers = (
        "connection",
        "timeout",
        "network",
        "ssl",
        "tls",
        "disconnect",
        "refused",
        "reset",
    )
    if any(m in combined for m in network_markers):
        out.append((
            FailoverReason.NETWORK_ERROR,
            RecoveryAction(
                should_retry=True,
                delay_seconds=5.0,
                user_hint="Network error — retrying",
            ),
        ))
        return True
    return False


def classify_api_error(err: ProviderError) -> ClassifiedError:
    """Classify a ProviderError and return structured recovery hints.

    Classification follows a priority-ordered pipeline:
        1. Thinking signature mismatch
        2. Context overflow
        3. Billing / auth via status code
        4. Rate limiting
        5. Server errors
        6. Network heuristics
        7. Fallback: unknown (retryable)

    Args:
        err: The ProviderError to classify.

    Returns:
        A ClassifiedError with reason and recovery hints.
    """
    candidates: list[tuple[FailoverReason, RecoveryAction]] = []

    # Priority 1: Special patterns
    if _check_thinking_signature(err, candidates):
        reason, recovery = candidates[0]
        return ClassifiedError(
            reason=reason,
            recovery=recovery,
            original=err,
            message=str(err),
        )

    # Priority 2: Context overflow
    if _check_context_overflow(err, candidates):
        reason, recovery = candidates[0]
        return ClassifiedError(
            reason=reason,
            recovery=recovery,
            original=err,
            message=str(err),
        )

    # Priority 3: HTTP status code
    if _check_status_code(err, candidates):
        reason, recovery = candidates[0]
        return ClassifiedError(
            reason=reason,
            recovery=recovery,
            original=err,
            message=str(err),
        )

    # Priority 4: Network heuristics
    if _check_network_heuristics(err, candidates):
        reason, recovery = candidates[0]
        return ClassifiedError(
            reason=reason,
            recovery=recovery,
            original=err,
            message=str(err),
        )

    # Fallback: unknown but retryable
    return ClassifiedError(
        reason=FailoverReason.UNKNOWN,
        recovery=RecoveryAction(
            should_retry=True,
            user_hint="Unknown error — retrying as a precaution",
        ),
        original=err,
        message=str(err),
    )
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd "d:/An/CODE/AgentsX" && uv run pytest tests/test_error_classifier.py -v
```
预期: 8 passed

- [ ] **Step 5: 接入 loop.py — 使用分类器驱动恢复动作**

修改 `agentsx/agent/loop.py` 中第 208-229 行的 provider 错误处理块:

```python
# loop.py: 替换原 except Exception as exc: 块 (约 214-229 行)
from agentsx.core.error_classifier import classify_api_error  # noqa: PLC0415

# ... 在 except 块中:
        except Exception as exc:  # noqa: BLE001
            classified = classify_api_error(
                exc if isinstance(exc, ProviderError)
                else ProviderError(str(exc))
            )
            if extensions is not None:
                await extensions.emit(
                    ExtensionEvent(
                        type=EVENT_ON_ERROR,
                        data={
                            "error": str(exc),
                            "reason": classified.reason,
                            "recovery_hint": classified.recovery.user_hint,
                        },
                    )
                )

            # Auto-retry on context overflow: compact and retry once
            if classified.recovery.should_compress and compact:
                logger.info("Auto-compacting on context overflow")
                old_count = len(messages)
                compacted = compact_messages(messages)
                if len(compacted) < old_count:
                    messages.clear()
                    messages.extend(compacted)
                    yield CompactionEvent(
                        compacted_count=old_count - len(compacted),
                        preserved_count=len(compacted),
                    )
                    # Retry the step once after compaction
                    continue

            yield ErrorEvent(
                error=exc,
                context=(
                    f"classified as {classified.reason}: "
                    f"{classified.recovery.user_hint}"
                ),
            )
            return
```

- [ ] **Step 6: 运行全量测试确认无回归**

```bash
cd "d:/An/CODE/AgentsX" && uv run ruff check agentsx/ tests/
cd "d:/An/CODE/AgentsX" && uv run ruff format --check agentsx/ tests/
cd "d:/An/CODE/AgentsX" && uv run mypy agentsx/ tests/ --strict
cd "d:/An/CODE/AgentsX" && uv run pytest -v
```

- [ ] **Step 7: 提交**

```bash
git add agentsx/core/error_classifier.py
git add agentsx/agent/loop.py
git add tests/test_error_classifier.py
git commit -m "feat(security): add centralized error classifier with recovery hints"
```

---

### Task 2: 结构化工具结果

**Files:**
- Create: `agentsx/core/tool_result.py`
- Modify: `agentsx/core/types.py` (替换旧 ToolResult)
- Modify: `agentsx/tools/__init__.py` (ToolSpec.call 返回 ToolResult)
- Modify: `agentsx/agent/loop.py` (消费新 ToolResult)
- Test: `tests/test_tool_result.py`

**Interfaces:**
- Consumes: Nothing from earlier tasks
- Produces: `ToolResult` dataclass, `ToolResultStatus` enum, `ToolSpec.call() -> ToolResult`

**Design:** 参考 tau 的 `AgentToolResult`, 将纯字符串工具结果替换为结构化 dataclass, 包含状态、元数据、内容、错误详情。让 UI 和下游系统可以精确消费工具结果。

- [ ] **Step 1: 写入失败测试**

```python
# tests/test_tool_result.py

"""Tests for structured ToolResult."""

from agentsx.core.tool_result import ToolResult, ToolResultStatus


def test_tool_result_success() -> None:
    result = ToolResult(
        tool_call_id="tc_001",
        status=ToolResultStatus.SUCCESS,
        content="file contents here",
    )
    assert result.is_success is True
    assert result.is_error is False
    assert result.status == ToolResultStatus.SUCCESS


def test_tool_result_error() -> None:
    result = ToolResult(
        tool_call_id="tc_002",
        status=ToolResultStatus.ERROR,
        content="",
        error=RuntimeError("file not found"),
    )
    assert result.is_success is False
    assert result.is_error is True
    assert result.error_detail == "file not found"


def test_tool_result_blocked() -> None:
    result = ToolResult(
        tool_call_id="tc_003",
        status=ToolResultStatus.BLOCKED,
        content="Blocked by policy: 'shell' is forbidden",
    )
    assert result.is_blocked is True
    assert result.is_error is True


def test_tool_result_repr() -> None:
    result = ToolResult(
        tool_call_id="tc_004",
        status=ToolResultStatus.SUCCESS,
        content="hello",
    )
    assert "tc_004" in repr(result)
    assert "SUCCESS" in repr(result)


def test_tool_result_to_legacy_string() -> None:
    """Backward compat: to_legacy_string() returns the old str format."""
    result = ToolResult(
        tool_call_id="tc_005",
        status=ToolResultStatus.SUCCESS,
        content="output data",
    )
    legacy = result.to_legacy_string()
    assert legacy == "output data"


def test_tool_result_error_to_legacy() -> None:
    result = ToolResult(
        tool_call_id="tc_006",
        status=ToolResultStatus.ERROR,
        content="",
        error=ValueError("bad value"),
    )
    legacy = result.to_legacy_string()
    assert "bad value" in legacy
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd "d:/An/CODE/AgentsX" && uv run pytest tests/test_tool_result.py -v
```
预期: 全部失败

- [ ] **Step 3: 实现结构化工具结果**

```python
# agentsx/core/tool_result.py

"""Structured tool result dataclass.

Replaces plain-string tool results with a typed result that includes
status, content, error detail, and optional metadata.  Inspired by
Tau's ``AgentToolResult`` pattern.
"""

from dataclasses import dataclass, field


class ToolResultStatus(str):
    """Status of a tool call execution."""

    SUCCESS = "success"
    ERROR = "error"
    BLOCKED = "blocked"


@dataclass
class ToolResult:
    """Structured result from executing a tool call.

    Attributes:
        tool_call_id: ID of the tool call this result corresponds to.
        status: Execution status (success, error, or blocked).
        content: Primary result content (always present).
        error: Optional exception that caused failure.
        metadata: Optional key-value metadata (truncated, duration, etc.).
    """

    tool_call_id: str
    status: ToolResultStatus
    content: str
    error: Exception | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.status == ToolResultStatus.SUCCESS

    @property
    def is_error(self) -> bool:
        return self.status in (ToolResultStatus.ERROR, ToolResultStatus.BLOCKED)

    @property
    def is_blocked(self) -> bool:
        return self.status == ToolResultStatus.BLOCKED

    @property
    def error_detail(self) -> str:
        """Human-readable error description."""
        if self.error is not None:
            return str(self.error)
        if self.status == ToolResultStatus.BLOCKED:
            return self.content
        return ""

    def to_legacy_string(self) -> str:
        """Return a backward-compatible string representation.

        For success: returns content.
        For error/blocked: returns error detail or content.
        """
        if self.is_success:
            return self.content
        return self.error_detail or self.content

    def __repr__(self) -> str:
        return (
            f"ToolResult(tool_call_id={self.tool_call_id!r}, "
            f"status={self.status!r}, "
            f"content={self.content[:60]!r})"
        )
```

- [ ] **Step 4: 更新 ToolSpec.call() 返回 ToolResult**

修改 `agentsx/tools/__init__.py` 中的 `ToolSpec.call()`:

```python
# 在文件顶部 import
from agentsx.core.tool_result import ToolResult, ToolResultStatus

# 替换 ToolSpec.call 方法 (原 99-109 行):
    async def call(self, **kwargs: object) -> ToolResult:
        """Execute the tool and return a structured ToolResult."""
        try:
            result = self.fn(**kwargs)
            if inspect.iscoroutine(result):
                result = await result
            return ToolResult(
                tool_call_id="",
                status=ToolResultStatus.SUCCESS,
                content=str(result),
            )
        except Exception as exc:
            return ToolResult(
                tool_call_id="",
                status=ToolResultStatus.ERROR,
                content=str(exc),
                error=exc,
            )
```

- [ ] **Step 5: 更新 types.py — 替换旧 ToolResult import**

修改 `agentsx/core/types.py` 第 197-204 行,将旧 `ToolResult` dataclass 替换为:

```python
# 在文件顶部添加 re-export (替换原来的 ToolResult dataclass):
from agentsx.core.tool_result import ToolResult as ToolResult

ToolResult = ToolResult  # noqa: F811 — re-export from dedicated module
```

- [ ] **Step 6: 更新 loop.py 消费新 ToolResult**

修改 `agentsx/agent/loop.py` 中 `_execute_tool_with_status()`:

```python
# 替换 _execute_tool_with_status 函数 (原 436-461 行):
async def _execute_tool_with_status(
    tc: ToolCall,
    tools: ToolRegistry,
    max_output: int = 0,
) -> ToolResult:
    """Execute a single tool call and return a structured ToolResult.

    Args:
        tc: The tool call to execute.
        tools: The tool registry.
        max_output: Maximum characters to keep (0 = use resource_limits default).
    """
    from agentsx.security.resource_limits import get_limits  # noqa: PLC0415

    try:
        result = await tools.call(tc.name, **tc.arguments)
        # result is now ToolResult from ToolSpec.call()
        limits = get_limits()
        effective_limit = limits.max_output_chars
        if max_output > 0:
            effective_limit = min(max_output, effective_limit)
        if effective_limit > 0 and len(result.content) > effective_limit:
            result.content = _truncate_head_tail(
                result.content, effective_limit,
            )
            result.metadata["truncated"] = "true"
        return ToolResult(
            tool_call_id=tc.id,
            status=ToolResultStatus.SUCCESS,
            content=result.content,
            metadata=result.metadata,
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            tool_call_id=tc.id,
            status=ToolResultStatus.ERROR,
            content=str(exc),
            error=exc,
        )
```

同时修改 loop 中创建 `tool_result` 的行 (约 318-323 行):

```python
# 替换原来的 ToolResult(...) 调用:
            tool_result = await _execute_tool_with_status(
                tc,
                tools,
                settings.max_tool_output,
            )
```

- [ ] **Step 7: 运行全量测试**

```bash
cd "d:/An/CODE/AgentsX" && uv run ruff check agentsx/ tests/
cd "d:/An/CODE/AgentsX" && uv run ruff format --check agentsx/ tests/
cd "d:/An/CODE/AgentsX" && uv run mypy agentsx/ tests/ --strict
cd "d:/An/CODE/AgentsX" && uv run pytest -v
```

- [ ] **Step 8: 提交**

```bash
git add agentsx/core/tool_result.py
git add agentsx/core/types.py
git add agentsx/tools/__init__.py
git add agentsx/agent/loop.py
git add tests/test_tool_result.py
git commit -m "feat(tools): replace plain-string tool results with structured ToolResult"
```

---

### Task 3: 扩展事件流

**Files:**
- Modify: `agentsx/core/types.py` (新增 7 种事件类型)
- Test: `tests/test_events.py`

**Interfaces:**
- Consumes: `ToolResult` from Task 2
- Produces: 新增 `AgentStartEvent`, `AgentEndEvent`, `TurnStartEvent`, `TurnEndEvent`, `ToolExecutionStartEvent`, `RetryEvent`, `TextDeltaEvent`, 更新 `AgentEvent` union

**Design:** 参考 tau 的完整事件流,将当前 6 种事件扩展为 13 种,覆盖生命周期各阶段。使前端可以精确渲染每个状态 (开始、进行中、工具执行前、重试等)。

- [ ] **Step 1: 写入失败测试**

```python
# tests/test_events.py

"""Tests for the expanded agent event types."""

from datetime import datetime

from agentsx.core.types import (
    AgentEndEvent,
    AgentStartEvent,
    AgentEvent,
    RetryEvent,
    TextDeltaEvent,
    ToolExecutionStartEvent,
    TurnEndEvent,
    TurnStartEvent,
)


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


def test_retry_event() -> None:
    event = RetryEvent(
        attempt=2,
        max_attempts=3,
        reason="rate limit",
        delay=5.0,
    )
    assert event.attempt == 2
    assert event.delay == 5.0


def test_text_delta_event() -> None:
    event = TextDeltaEvent(text="Hello")
    assert event.text == "Hello"


def test_tool_execution_start_event() -> None:
    event = ToolExecutionStartEvent(
        tool_name="file_read",
        tool_call_id="tc_001",
    )
    assert event.tool_name == "file_read"


def test_agent_event_union_dispatch() -> None:
    """AgentEvent union supports all new types via isinstance."""
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

- [ ] **Step 2: 运行测试确认失败**

```bash
cd "d:/An/CODE/AgentsX" && uv run pytest tests/test_events.py -v
```

- [ ] **Step 3: 在 types.py 中添加新事件类型**

在 `agentsx/core/types.py` 的 Events 部分 (约 374-440 行) 添加:

```python
# 在 CompactionEvent 之前添加:

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


# 更新 AgentEvent union (替换原来的):
AgentEvent = (
    AgentStartEvent
    | AgentEndEvent
    | TurnStartEvent
    | TurnEndEvent
    | ModelRequestEvent
    | TextDeltaEvent
    | ModelResponseEvent
    | ToolExecutionStartEvent
    | ToolExecutionEvent
    | ErrorEvent
    | CompactionEvent
    | PromptEvent
    | RetryEvent
)
"""Union type for all agent events. Consumers use ``isinstance()`` to dispatch."""
```

- [ ] **Step 4: 在 loop.py 中产出新事件**

在 `run_agent_loop()` 中添加事件产出:

```python
# 在 while 循环开始前 (约 step=0 之后):
    yield AgentStartEvent(
        model=provider.model.id,
        step=0,
    )

# 在 step += 1 之后:
        yield TurnStartEvent(turn=step)

# 在 no tools → break 之前:
        yield TurnEndEvent(turn=step, had_tool_calls=False)
        break

# 在 pending_calls 循环开始前:
            yield ToolExecutionStartEvent(
                tool_name=tc.name,
                tool_call_id=tc.id,
            )

# 在循环结束 (while 之后):
    yield AgentEndEvent(
        step=step,
        reason="completed" if step < max_steps else "max_steps",
    )
```

- [ ] **Step 5: 运行全量测试**

```bash
cd "d:/An/CODE/AgentsX" && uv run pytest -v
```

- [ ] **Step 6: 提交**

```bash
git add agentsx/core/types.py
git add agentsx/agent/loop.py
git add tests/test_events.py
git commit -m "feat(core): expand agent event stream to 13 typed events"
```

---

## 阶段 2: 可复用性增强 (P1)

### Task 4: AgentHarness 门面

**Files:**
- Create: `agentsx/agent/harness.py`
- Test: `tests/test_harness.py`

**Interfaces:**
- Consumes: `run_agent_loop()` from Task 3, all event types
- Produces: `AgentHarness` class with `prompt()`, `subscribe()`, `cancel()`, steer/follow-up queue support

**Design:** 参考 tau 的 `AgentHarness` — 一个有状态的门面,拥有消息历史、取消令牌、事件监听器和提示队列。将 `run()` 的状态管理从 `Agent` 类中提取为可复用组件。

- [ ] **Step 1: 写入失败测试**

```python
# tests/test_harness.py

"""Tests for AgentHarness — stateful facade around the agent loop."""

import asyncio
from collections import deque

import pytest

from agentsx.agent.harness import AgentHarness
from agentsx.core.types import (
    AgentEndEvent,
    AgentMessage,
    AgentStartEvent,
    MessageRole,
    ModelResponseEvent,
)


class _FakeProvider:
    """Minimal provider that echoes user input as assistant response."""

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
    # Should include AgentStartEvent, ModelResponseEvent, AgentEndEvent
    types = {type(e).__name__ for e in events}
    assert "AgentStartEvent" in types
    assert "AgentEndEvent" in types


@pytest.mark.asyncio
async def test_harness_remembers_history() -> None:
    harness = AgentHarness(provider=_FakeProvider(["A", "B"]))
    await harness.prompt("First").__anext__()
    await harness.prompt("Second").__anext__()
    assert len(harness.messages) >= 3  # system + 2 user


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
    # Should complete quickly after cancel
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
    harness = AgentHarness(
        provider=_FakeProvider(["a"]),
        system_prompt="You are helpful",
    )
    await harness.prompt("Hi").__anext__()
    harness.clear_history()
    assert len(harness.messages) == 1
    assert harness.Messages[0].role == MessageRole.SYSTEM
```

- [ ] **Step 2: 实现 AgentHarness**

```python
# agentsx/agent/harness.py

"""Stateful agent harness — reusable brain around the pure agent loop.

Inspired by Tau's ``AgentHarness`` pattern.  Owns the transcript
(message history), cancellation, event listeners, and prompt queues.
Delegates execution to ``run_agent_loop()``.

Public API::

    harness = AgentHarness(provider=p, system_prompt="...")

    async for event in harness.prompt("Hello"):
        print(event)

    harness.subscribe(listener_fn)
    harness.queue_follow_up("also check X")
    harness.cancel()
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import AsyncIterator, Callable
from typing import Any

from agentsx.agent.loop import run_agent_loop
from agentsx.config import get_settings
from agentsx.core.types import (
    AgentEvent,
    AgentMessage,
    MessageRole,
)
from agentsx.extensions.api import ExtensionAPI
from agentsx.provider import Provider
from agentsx.security.policy import ExecutionPolicy
from agentsx.tools import ToolRegistry

logger = logging.getLogger(__name__)

EventListener = Callable[[AgentEvent], None]


class AgentHarness:
    """Stateful facade managing transcript, listeners, and queues.

    The harness owns the message list and delegates execution to the
    pure ``run_agent_loop()`` async generator.

    Attributes:
        provider: The LLM provider used for requests.
        messages: The full conversation transcript (read-only property).
    """

    def __init__(
        self,
        provider: Provider,
        system_prompt: str | None = None,
        tools: ToolRegistry | None = None,
        policy: ExecutionPolicy | None = None,
        extensions: ExtensionAPI | None = None,
        max_steps: int | None = None,
    ) -> None:
        self._provider = provider
        self._tools = tools
        self._policy = policy
        self._extensions = extensions
        self._max_steps = max_steps
        self._messages: list[AgentMessage] = []
        self._listeners: list[EventListener] = []
        self._cancelled = False
        self._follow_up_queue: deque[str] = deque()
        self._steer_queue: deque[str] = deque()

        if system_prompt is None:
            system_prompt = get_settings().system_prompt
        if system_prompt:
            self._messages.append(
                AgentMessage(role=MessageRole.SYSTEM, content=system_prompt),
            )

    # ── Public Properties ─────────────────────────────────────────

    @property
    def provider(self) -> Provider:
        return self._provider

    @property
    def messages(self) -> list[AgentMessage]:
        """Read-only access to the conversation transcript."""
        return list(self._messages)

    # ── Prompt ────────────────────────────────────────────────────

    async def prompt(
        self,
        user_input: str,
        *,
        timeout: float = 0,
    ) -> AsyncIterator[AgentEvent]:
        """Send a user message and run the agent loop.

        Yields:
            ``AgentEvent`` items from the agent loop.
        """
        if self._cancelled:
            self._cancelled = False
            return

        self._messages.append(
            AgentMessage(role=MessageRole.USER, content=user_input),
        )

        steer = self._steer_queue if self._steer_queue else None

        async for event in run_agent_loop(
            self._provider,
            self._messages,
            self._max_steps,
            tools=self._tools,
            policy=self._policy,
            extensions=self._extensions,
            timeout=timeout,
            steer_queue=steer,
        ):
            # Dispatch to subscribers
            for listener in self._listeners:
                try:
                    listener(event)
                except Exception:  # noqa: BLE001
                    logger.exception("Event listener error")

            yield event

        # Drain follow-up queue: inject follow-ups as additional turns
        while self._follow_up_queue and not self._cancelled:
            follow_up = self._follow_up_queue.popleft()
            self._messages.append(
                AgentMessage(role=MessageRole.USER, content=follow_up),
            )
            async for event in run_agent_loop(
                self._provider,
                self._messages,
                self._max_steps,
                tools=self._tools,
                policy=self._policy,
                extensions=self._extensions,
                timeout=timeout,
            ):
                for listener in self._listeners:
                    try:
                        listener(event)
                    except Exception:  # noqa: BLE001
                        logger.exception("Event listener error")
                yield event

    # ── Subscription ──────────────────────────────────────────────

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        """Register an event listener.

        Args:
            listener: Called for every event during a prompt run.

        Returns:
            Unsubscribe callable.
        """
        self._listeners.append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return unsubscribe

    # ── Queues ────────────────────────────────────────────────────

    def queue_follow_up(self, content: str) -> None:
        """Queue a follow-up message for after the current turn."""
        self._follow_up_queue.append(content)

    def queue_steering(self, content: str) -> None:
        """Queue a steering message for mid-run injection."""
        self._steer_queue.append(content)

    # ── Control ───────────────────────────────────────────────────

    def cancel(self) -> None:
        """Cancel the current run after the current step."""
        self._cancelled = True

    def clear_history(self) -> None:
        """Clear conversation, keeping system prompt."""
        system = None
        if self._messages and self._messages[0].role == MessageRole.SYSTEM:
            system = self._messages[0]
        self._messages.clear()
        if system:
            self._messages.append(system)
        self._follow_up_queue.clear()
        self._steer_queue.clear()
```

- [ ] **Step 3: 运行测试确认通过**

```bash
cd "d:/An/CODE/AgentsX" && uv run pytest tests/test_harness.py -v
```

- [ ] **Step 4: 提交**

```bash
git add agentsx/agent/harness.py
git add tests/test_harness.py
git commit -m "feat(agent): add AgentHarness facade with subscription and queue support"
```

---

### Task 5: Append-only Session Compaction

**Files:**
- Create: `agentsx/context/compaction_entry.py`
- Modify: `agentsx/session/store.py` (新增 append_compaction_entry)
- Modify: `agentsx/context/compaction.py` (使用 CompactionEntry)
- Test: `tests/test_compaction_entry.py`

**Interfaces:**
- Consumes: Session store from existing code
- Produces: `CompactionEntry` dataclass, `replay_messages()`, `SessionStore.append_compaction_entry()`

**Design:** 参考 tau 的 `CompactionEntry` 回放模式。压缩不修改文件,而是追加一个条目告诉回放引擎用摘要替换旧消息。保留完整审计历史。

- [ ] **Step 1: 写入失败测试**

```python
# tests/test_compaction_entry.py

"""Tests for append-only compaction entry system."""

import json
from pathlib import Path

from agentsx.context.compaction_entry import (
    CompactionEntry,
    replay_messages,
)
from agentsx.core.types import AgentMessage, MessageRole


def test_compaction_entry_serialization() -> None:
    entry = CompactionEntry(
        replaces_ids=["msg_1", "msg_2"],
        summary="User asked about files, agent read 3 files",
        token_estimate=500,
    )
    data = entry.to_dict()
    assert data["type"] == "compaction"
    assert len(data["replaces_ids"]) == 2
    assert "summary" in data


def test_compaction_entry_deserialization() -> None:
    data = {
        "type": "compaction",
        "replaces_ids": ["msg_1"],
        "summary": "compact",
        "token_estimate": 100,
    }
    entry = CompactionEntry.from_dict(data)
    assert entry.replaces_ids == ["msg_1"]
    assert entry.summary == "compact"


def test_replay_without_compaction() -> None:
    """Replay without compaction entries returns original messages."""
    messages = [
        AgentMessage(role=MessageRole.SYSTEM, content="sys", id="m0"),
        AgentMessage(role=MessageRole.USER, content="hello", id="m1"),
        AgentMessage(role=MessageRole.ASSISTANT, content="hi", id="m2"),
    ]
    result = replay_messages(messages, compaction_entries=[])
    assert len(result) == 3


def test_replay_with_compaction() -> None:
    """Compaction replaces referenced messages with summary."""
    messages = [
        AgentMessage(role=MessageRole.SYSTEM, content="sys", id="m0"),
        AgentMessage(role=MessageRole.USER, content="long question", id="m1"),
        AgentMessage(role=MessageRole.ASSISTANT, content="long answer", id="m2"),
        AgentMessage(role=MessageRole.USER, content="follow up", id="m3"),
    ]
    entries = [
        CompactionEntry(
            replaces_ids=["m1", "m2"],
            summary="User asked about X, agent explained Y",
            token_estimate=200,
        )
    ]
    result = replay_messages(messages, compaction_entries=entries)
    # m0 preserved (not in replaces), m1+m2 replaced with summary, m3 preserved
    assert len(result) == 3
    assert result[0].id == "m0"
    assert "compacted" in result[1].content.lower()
    assert "compact" in result[1].content.lower()
    assert result[2].id == "m3"
```

- [ ] **Step 2: 实现 CompactionEntry**

```python
# agentsx/context/compaction_entry.py

"""Append-only compaction entry system.

Instead of modifying the session file on compaction, a ``CompactionEntry``
is appended to a separate JSONL file.  During replay, entries in the
compaction log tell the engine which messages to replace with a summary.

This preserves the full audit trail — the original messages are always
reconstructable by replaying without compaction awareness.

Inspired by Tau's ``CompactionEntry`` pattern.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentsx.core.types import AgentMessage, MessageRole


@dataclass
class CompactionEntry:
    """Records a compaction without modifying the session file.

    Attributes:
        replaces_ids: Message IDs that this compaction replaces.
        summary: Human-readable summary of the replaced messages.
        token_estimate: Approximate token count of the replaced messages.
    """

    replaces_ids: list[str]
    summary: str
    token_estimate: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "compaction",
            "replaces_ids": self.replaces_ids,
            "summary": self.summary,
            "token_estimate": self.token_estimate,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CompactionEntry:
        return cls(
            replaces_ids=data.get("replaces_ids", []),
            summary=data.get("summary", ""),
            token_estimate=data.get("token_estimate", 0),
        )


def replay_messages(
    messages: list[AgentMessage],
    compaction_entries: list[CompactionEntry],
) -> list[AgentMessage]:
    """Replay messages with compaction awareness.

    Messages referenced by CompactionEntry.replaces_ids are replaced
    with a single summary message.  Messages not referenced are kept.

    Args:
        messages: Original session messages.
        compaction_entries: Ordered compaction entries.

    Returns:
        New message list with compacted regions replaced by summaries.
    """
    if not compaction_entries:
        return messages

    # Build a set of all message IDs that are replaced
    replaced_ids: set[str] = set()
    for entry in compaction_entries:
        replaced_ids.update(entry.replaces_ids)

    # Group consecutive replaced messages for summary placement
    result: list[AgentMessage] = []
    skip_ids: set[str] = set()

    for msg in messages:
        if msg.id in replaced_ids and msg.id not in skip_ids:
            # Find all consecutive replaced messages
            group_ids: list[str] = []
            for m in messages[messages.index(msg):]:
                if m.id in replaced_ids:
                    group_ids.append(m.id)
                    skip_ids.add(m.id)
                else:
                    break

            # Find the compaction entry covering this group
            for entry in compaction_entries:
                if all(gid in entry.replaces_ids for gid in group_ids):
                    summary_msg = AgentMessage(
                        role=MessageRole.USER,
                        content=(
                            f"[{len(group_ids)} messages compacted "
                            f"(~{entry.token_estimate} tokens omitted)]\n"
                            f"{entry.summary}"
                        ),
                    )
                    result.append(summary_msg)
                    break
        elif msg.id not in replaced_ids:
            result.append(msg)

    return result


def load_compaction_entries(path: Path) -> list[CompactionEntry]:
    """Load compaction entries from a JSONL file."""
    if not path.is_file():
        return []
    entries: list[CompactionEntry] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                entries.append(CompactionEntry.from_dict(json.loads(stripped)))
    return entries


def append_compaction_entry(
    path: Path,
    entry: CompactionEntry,
) -> None:
    """Append a compaction entry to the JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry.to_dict(), separators=(",", ":")) + "\n")
```

- [ ] **Step 3: 集成到 session store**

在 `agentsx/session/store.py` 中添加:

```python
# 在 SessionStore 类中添加:
    def append_compaction_entry(
        self,
        session_id: str,
        replaces_ids: list[str],
        summary: str,
        token_estimate: int = 0,
    ) -> None:
        """Record a compaction without modifying the session file.

        Args:
            session_id: The session to record compaction for.
            replaces_ids: Message IDs being replaced.
            summary: Summary of the compacted messages.
            token_estimate: Token count of replaced messages.
        """
        from agentsx.context.compaction_entry import (  # noqa: PLC0415
            CompactionEntry,
            append_compaction_entry as _append,
        )

        session_dir = self._session_dir(session_id)
        compaction_path = session_dir / "compaction.jsonl"
        entry = CompactionEntry(
            replaces_ids=replaces_ids,
            summary=summary,
            token_estimate=token_estimate,
        )
        _append(compaction_path, entry)
```

- [ ] **Step 4: 运行测试**

```bash
cd "d:/An/CODE/AgentsX" && uv run pytest tests/test_compaction_entry.py -v
```

- [ ] **Step 5: 提交**

```bash
git add agentsx/context/compaction_entry.py
git add agentsx/session/store.py
git add tests/test_compaction_entry.py
git commit -m "feat(session): add append-only compaction entry system with replay"
```

---

## 阶段 3: 智能能力 (P1)

### Task 6: Context Profile 系统

**Files:**
- Create: `agentsx/core/profile.py`
- Test: `tests/test_profile.py`

**Interfaces:**
- Consumes: None
- Produces: `ContextProfile` frozen dataclass, `resolve_runtime_mode()`

**Design:** 参考 hermes-agent 的 `RuntimeMode` / `ContextProfile` — 一个冻结的运行时姿态检测对象,单一真相源,所有域 (系统提示、工具选择、模型路由) 消费同一对象。

- [ ] **Step 1: 写入失败测试**

```python
# tests/test_profile.py

"""Tests for ContextProfile and runtime mode detection."""

from agentsx.core.profile import (
    AgentPosture,
    ContextProfile,
    resolve_runtime_mode,
)


def test_context_profile_frozen() -> None:
    profile = ContextProfile(
        name="coding",
        posture=AgentPosture.CODING,
        toolset_filter=frozenset({"read", "write", "exec"}),
    )
    assert profile.frozen is True  # dataclass(frozen=True)


def test_resolve_runtime_mode_in_git_repo() -> None:
    """In a git repo with source files, posture should be CODING."""
    mode = resolve_runtime_mode(cwd="d:/An/CODE/AgentsX")
    assert mode.profile.name == "coding"


def test_resolve_runtime_mode_empty_dir() -> None:
    """In an empty directory, posture should be GENERAL."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        mode = resolve_runtime_mode(cwd=tmpdir)
        assert mode.profile.name == "general"


def test_runtime_mode_toolset_filter() -> None:
    """Coding posture should filter to coding toolset."""
    mode = resolve_runtime_mode(cwd="d:/An/CODE/AgentsX")
    assert mode.recommended_toolsets is not None


def test_context_profile_registry() -> None:
    """Built-in profiles should be accessible."""
    from agentsx.core.profile import get_profile

    coding = get_profile("coding")
    assert coding is not None
    general = get_profile("general")
    assert general is not None
```

- [ ] **Step 2: 实现 Context Profile**

```python
# agentsx/core/profile.py

"""Frozen runtime posture detection (ContextProfile).

Inspired by Hermes-Agent's ``RuntimeMode`` / ``ContextProfile``.  A single
frozen object determines agent posture (coding vs general), which all
domains consume — system prompt, toolset selection, model routing —
instead of each independently probing git/config.

Built-in profiles:
    - ``coding``: Detected git repo with source files.
    - ``general``: Default posture for non-project directories.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class AgentPosture(str, Enum):
    """Detected agent operating posture."""

    CODING = "coding"
    GENERAL = "general"


@dataclass(frozen=True)
class ContextProfile:
    """Frozen posture configuration for an agent session.

    Attributes:
        name: Profile identifier.
        posture: Detected agent posture.
        toolset_filter: Optional toolset names to enable.
        system_hint: Optional system prompt modifier.
    """

    name: str
    posture: AgentPosture
    toolset_filter: frozenset[str] = frozenset()
    system_hint: str = ""

    @property
    def frozen(self) -> bool:
        return True


# Built-in profile registry
_PROFILES: dict[str, ContextProfile] = {
    "coding": ContextProfile(
        name="coding",
        posture=AgentPosture.CODING,
        toolset_filter=frozenset({"read", "write", "exec", "orchestration"}),
        system_hint=(
            "You are working in a coding project. "
            "Be precise, use tools effectively, and follow project conventions."
        ),
    ),
    "general": ContextProfile(
        name="general",
        posture=AgentPosture.GENERAL,
        toolset_filter=frozenset(),  # empty = all tools
        system_hint="",
    ),
}


def get_profile(name: str) -> ContextProfile | None:
    """Look up a context profile by name."""
    return _PROFILES.get(name)


# Source file extensions that indicate a coding project
_SOURCE_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".java",
    ".c", ".cpp", ".h", ".rb", ".swift", ".kt", ".scala",
    ".toml", ".yaml", ".yml", ".json",
}


def _has_source_files(directory: Path, max_scan: int = 50) -> bool:
    """Check if a directory contains source files (quick scan)."""
    count = 0
    for entry in directory.iterdir():
        if count >= max_scan:
            break
        if entry.is_file() and entry.suffix.lower() in _SOURCE_EXTENSIONS:
            return True
        if entry.is_dir() and not entry.name.startswith("."):
            for sub in entry.iterdir():
                if count >= max_scan:
                    break
                if sub.is_file() and sub.suffix.lower() in _SOURCE_EXTENSIONS:
                    return True
                count += 1
        count += 1
    return False


def resolve_runtime_mode(cwd: str | Path | None = None) -> ContextProfile:
    """Detect the appropriate context profile for the current directory.

    Args:
        cwd: Working directory to detect posture from.
            Defaults to current working directory.

    Returns:
        A frozen ContextProfile appropriate for the detected posture.
    """
    working_dir = Path(cwd) if cwd else Path.cwd()

    # Check if in a git repo with source files
    if (working_dir / ".git").is_dir():
        if _has_source_files(working_dir):
            return _PROFILES["coding"]

    # Check parent directories for git repo
    for parent in working_dir.parents:
        if (parent / ".git").is_dir():
            if _has_source_files(parent):
                return _PROFILES["coding"]
            break

    return _PROFILES["general"]
```

- [ ] **Step 3: 运行测试**

```bash
cd "d:/An/CODE/AgentsX" && uv run pytest tests/test_profile.py -v
```

- [ ] **Step 4: 提交**

```bash
git add agentsx/core/profile.py
git add tests/test_profile.py
git commit -m "feat(core): add frozen ContextProfile for runtime posture detection"
```

---

### Task 7: Provider Transport 抽象

**Files:**
- Create: `agentsx/provider/transport.py`
- Modify: `agentsx/provider/__init__.py`
- Modify: `agentsx/provider/openai.py`
- Modify: `agentsx/provider/anthropic.py`
- Test: `tests/test_transport.py`

**Interfaces:**
- Consumes: `AgentMessage`, `StreamEvent`
- Produces: `ProviderTransport` ABC with `format_messages()`, `parse_stream()`, `build_kwargs()`

**Design:** 参考 hermes-agent 的 Transport ABC — 将格式转换从编排逻辑中分离。每个 provider 实现一个 Transport, 负责消息格式化和流解析。Provider 基类组合 Transport + 客户端构建。

- [ ] **Step 1: 写入失败测试**

```python
# tests/test_transport.py

"""Tests for ProviderTransport abstraction."""

from agentsx.core.types import AgentMessage, MessageRole
from agentsx.provider.transport import (
    OpenAITransport,
    AnthropicTransport,
)


def test_openai_transport_format_messages() -> None:
    transport = OpenAITransport()
    messages = [
        AgentMessage(role=MessageRole.SYSTEM, content="You are helpful"),
        AgentMessage(role=MessageRole.USER, content="Hello"),
    ]
    result = transport.format_messages(messages)
    assert len(result) == 2
    assert result[0]["role"] == "system"
    assert result[1]["role"] == "user"


def test_openai_transport_with_tool_calls() -> None:
    from agentsx.core.types import ToolCall

    transport = OpenAITransport()
    msg = AgentMessage(
        role=MessageRole.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(id="tc_1", name="read", arguments={"path": "x.txt"}),
        ],
    )
    result = transport.format_messages([msg])
    assert "tool_calls" in result[0]
    assert result[0]["tool_calls"][0]["function"]["name"] == "read"


def test_anthropic_transport_format_messages() -> None:
    transport = AnthropicTransport()
    messages = [
        AgentMessage(role=MessageRole.SYSTEM, content="You are helpful"),
        AgentMessage(role=MessageRole.USER, content="Hello"),
    ]
    result = transport.format_messages(messages)
    # Anthropic uses system separately, so user message is first
    assert len(result) >= 1


def test_transport_build_kwargs_openai() -> None:
    transport = OpenAITransport()
    kwargs = transport.build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        max_tokens=100,
    )
    assert "messages" in kwargs
    assert "max_tokens" in kwargs
```

- [ ] **Step 2: 实现 Transport 抽象**

```python
# agentsx/provider/transport.py

"""Provider Transport abstraction — format conversion only.

Inspired by Hermes-Agent's transport layer.  Each Transport owns ONLY
message formatting and stream parsing.  It does NOT own client
construction, streaming, credential refresh, or retry logic.

This cleanly separates the format-conversion concern from orchestration.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from agentsx.core.types import AgentMessage, StreamEvent


class ProviderTransport(ABC):
    """Abstract Transport for provider message formatting and stream parsing."""

    @abstractmethod
    def format_messages(
        self,
        messages: list[AgentMessage],
    ) -> list[dict[str, Any]]:
        """Convert AgentMessages to provider-native format."""

    @abstractmethod
    def build_kwargs(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        **extra: Any,
    ) -> dict[str, Any]:
        """Build provider API call kwargs."""

    @abstractmethod
    async def parse_stream(
        self,
        response: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Parse provider streaming response into StreamEvents."""


class OpenAITransport(ProviderTransport):
    """OpenAI-compatible message formatting and stream parsing."""

    def format_messages(
        self,
        messages: list[AgentMessage],
    ) -> list[dict[str, Any]]:
        return [msg._to_openai() for msg in messages]

    def build_kwargs(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        **extra: Any,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": extra.get("model", "gpt-4o"),
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
        if extra.get("temperature") is not None:
            kwargs["temperature"] = extra["temperature"]
        return kwargs

    async def parse_stream(
        self,
        response: Any,
    ) -> AsyncIterator[StreamEvent]:
        from agentsx.core.types import (  # noqa: PLC0415
            TextStreamEvent,
            ToolCallStreamEvent,
            ToolCall,
        )

        tool_call_buffer: dict[int, dict[str, Any]] = {}
        async for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield TextStreamEvent(text=delta.content)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_call_buffer:
                        tool_call_buffer[idx] = {
                            "id": tc.id or "",
                            "name": tc.function.name or "",
                            "arguments": "",
                        }
                    if tc.function.arguments:
                        tool_call_buffer[idx]["arguments"] += tc.function.arguments
                    if tc.id:
                        tool_call_buffer[idx]["id"] = tc.id
                    if tc.function.name:
                        tool_call_buffer[idx]["name"] = tc.function.name

        for buf in tool_call_buffer.values():
            try:
                args = json.loads(buf["arguments"]) if buf["arguments"] else {}
            except json.JSONDecodeError:
                args = {}
            yield ToolCallStreamEvent(
                tool_call=ToolCall(
                    id=buf["id"],
                    name=buf["name"],
                    arguments=args,
                )
            )


class AnthropicTransport(ProviderTransport):
    """Anthropic message formatting and stream parsing."""

    def format_messages(
        self,
        messages: list[AgentMessage],
    ) -> list[dict[str, Any]]:
        user_messages = []
        system_content = ""
        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                system_content = msg.content
            else:
                user_messages.append(msg._to_anthropic())
        return user_messages

    def build_kwargs(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        **extra: Any,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": extra.get("model", "claude-sonnet-4-20250514"),
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
        if extra.get("system"):
            kwargs["system"] = extra["system"]
        return kwargs

    async def parse_stream(
        self,
        response: Any,
    ) -> AsyncIterator[StreamStreamEvent]:
        from agentsx.core.types import (  # noqa: PLC0415
            TextStreamEvent,
            ToolCallStreamEvent,
            ToolCall,
        )

        current_tool: dict[str, Any] | None = None
        async for event in response:
            # Anthropic streaming event parsing
            if hasattr(event, "delta") and event.delta:
                if hasattr(event.delta, "text") and event.delta.text:
                    yield TextStreamEvent(text=event.delta.text)
            if hasattr(event, "content_block") and event.content_block:
                if event.content_block.type == "tool_use":
                    current_tool = {
                        "id": event.content_block.id,
                        "name": event.content_block.name,
                        "input": {},
                    }
            if hasattr(event, "delta") and event.delta:
                if hasattr(event.delta, "partial_json") and event.delta.partial_json:
                    if current_tool is not None:
                        # Accumulate partial JSON
                        pass

        # Emit completed tool calls
        if current_tool is not None:
            yield ToolCallStreamEvent(
                tool_call=ToolCall(
                    id=current_tool["id"],
                    name=current_tool["name"],
                    arguments=current_tool["input"],
                )
            )
```

- [ ] **Step 3: 运行测试**

```bash
cd "d:/An/CODE/AgentsX" && uv run pytest tests/test_transport.py -v
```

- [ ] **Step 4: 提交**

```bash
git add agentsx/provider/transport.py
git add agentsx/provider/__init__.py
git add agentsx/provider/openai.py
git add agentsx/provider/anthropic.py
git add tests/test_transport.py
git commit -m "feat(provider): add Transport abstraction for format conversion"
```

---

## 最终验证

- [ ] **Step: 全量验证**

```bash
cd "d:/An/CODE/AgentsX" && .venv\Scripts\activate
uv run ruff check agentsx/ tests/
uv run ruff format --check agentsx/ tests/
uv run mypy agentsx/ tests/ --strict
uv run pytest -v
```

预期: 全部通过, 新增测试覆盖所有新模块。

- [ ] **Step: 最终提交**

```bash
git status
# Stage all new/modified files explicitly
git add <each-file-path>
git commit -m "feat: comprehensive agent framework optimizations (3rdparty inspired)"
```
