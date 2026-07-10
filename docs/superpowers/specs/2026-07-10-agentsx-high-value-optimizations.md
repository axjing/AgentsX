# AgentsX 高价值优化设计文档

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将已创建但未使用的 Transport 系统集成到 Provider 层，添加 RetryEvent 产出、Compaction CLI 命令和 Session Resume 回放逻辑。

**Architecture:** 分 4 个独立优化项，均向后兼容。Transport 组合到 Provider 基类；RetryEvent 在 loop 层产出；CLI 添加 /compact 命令；SessionStore 自动回放 compaction.jsonl。

**Tech Stack:** Python 3.10+, async/await, dataclasses, typer, pytest

## Global Constraints

- Python 3.10 minimum, no `StrEnum` — use `(str, Enum)` mixin
- Full type annotations on all variables, parameters, return values; `Any` prohibited except unavoidable cases
- Google-style docstrings only; no Sphinx
- Line length max 88 characters (ruff config)
- `snake_case` for files/functions/variables, `PascalCase` for classes/exceptions
- No bare `except:` — always catch explicit exception types
- No mutable default parameters; use `None` placeholder
- All I/O-bound functions use `async def`
- No `from __future__` imports
- Validation: `ruff check` + `ruff format --check` + `mypy --strict` + `pytest -v` must all pass
- `git add <file-path>` only — `git add .` / `git add -A` prohibited
- 项目定位：harness 工程架构的个人通用智能体

---

## 优化项 1：Transport 集成到 Provider

### 现状

`transport.py` 已创建完整 ABC + OpenAITransport + AnthropicTransport，但 **未被任何 provider 使用**。`openai.py` 和 `anthropic.py` 各自硬编码 `format_messages()` 和流解析。

### 方案

让 `Provider` 基类组合一个 `ProviderTransport` 实例。子类提供 transport，`format_messages()` 和流解析委托给 transport。

### 关键变化

#### `agentsx/provider/__init__.py` — Provider 基类

在 `Provider.__init__` 中接受 `transport` 参数，`format_messages()` 默认委托：

```python
class Provider(ABC):
    model: Model
    tools: ToolRegistry | None = None
    profile: ProviderProfile | None = None
    transport: ProviderTransport | None = None

    def __init__(
        self,
        model: Model,
        transport: ProviderTransport | None = None,
    ) -> None:
        self.model = model
        self.tools = None
        self.profile = get_profile(model.provider_name)
        self.transport = transport

    def format_messages(self, messages: list[AgentMessage]) -> list[dict[str, Any]]:
        """Convert internal AgentMessages to provider-native format.

        If a transport is set, delegates to transport.format_messages().
        Subclasses may override for custom behavior.

        Args:
            messages: Conversation history in AgentMessage format.

        Returns:
            A list of dicts in the provider's message format.
        """
        if self.transport is not None:
            return self.transport.format_messages(messages)
        msg = "No transport configured and format_messages not overridden"
        raise NotImplementedError(msg)
```

#### `agentsx/provider/openai.py` — OpenAIProvider

在 `__init__` 中创建 `OpenAITransport`，`stream()` 使用 `transport.parse_stream()`：

```python
from agentsx.provider.transport import OpenAITransport

class OpenAIProvider(Provider):
    def __init__(self, model: Model, api_key: str = "", api_base: str = "") -> None:
        super().__init__(model, transport=OpenAITransport())
        # ... existing init code ...
```

`stream()` 方法改用 transport 解析：

```python
async def stream(self, messages: list[AgentMessage]) -> AsyncIterator[StreamEvent]:
    # ... build client, make request ...
    async for event in self.transport.parse_stream(response):
        yield event
```

#### `agentsx/provider/anthropic.py` — AnthropicProvider

同理：

```python
from agentsx.provider.transport import AnthropicTransport

class AnthropicProvider(Provider):
    def __init__(self, model: Model, api_key: str = "", api_base: str = "") -> None:
        super().__init__(model, transport=AnthropicTransport())
        # ... existing init code ...
```

### 测试

更新现有 provider 测试确保 transport 集成后行为不变。新增 2 个测试：
- `test_provider_format_messages_delegates_to_transport`
- `test_provider_without_transport_raises_not_implemented`

---

## 优化项 2：RetryEvent 产出

### 现状

`stream_with_retry()` 重试时只写 logger.warning，不产出任何事件。`RetryEvent` 类型已定义但从未被产出。

### 方案

在 `loop.py` 的 `except Exception` 块中，当错误分类器返回需要重试的类型时（`NETWORK_ERROR`、`SERVER_ERROR`、`RATE_LIMIT`），产出 `RetryEvent`。

### 关键变化

#### `agentsx/agent/loop.py`

在 `run_agent_loop()` 的 provider 错误处理中，产出 RetryEvent：

```python
from agentsx.core.error_classifier import classify_api_error, FailoverReason

# ... 在 except Exception as exc: 块中 ...
        except Exception as exc:  # noqa: BLE001
            classified = classify_api_error(
                exc if isinstance(exc, ProviderError)
                else ProviderError(str(exc))
            )

            # Emit RetryEvent for retryable errors (before the loop returns)
            if classified.recovery.should_retry:
                settings = get_settings()
                max_retries = settings.provider_retry_count
                delay = classified.recovery.delay_seconds or 1.0
                yield RetryEvent(
                    attempt=1,  # We don't track attempt count here
                    max_attempts=max_retries,
                    reason=classified.reason,
                    delay=delay,
                )

            # ... rest of error handling ...
```

**注意：** 实际重试发生在 `stream_with_retry()` 内部，loop 层无法准确知道当前是第几次重试。所以 RetryEvent 的 `attempt` 字段设为 1，表示"即将开始重试"。更精确的做法是在 provider 层产出，但这需要改 stream generator 的 yield 类型。

### 测试

新增 1 个测试：
- `test_retry_event_emitted_on_classified_error` — 验证网络错误时产出 RetryEvent

---

## 优化项 3：Compaction CLI 命令

### 现状

`CompactionEntry` 系统完整，`SessionStore.append_compaction_entry()` 可用，但 CLI 没有 `/compact` 命令。

### 方案

添加 `/compact` 和 `/compact force` 命令。

### 关键变化

#### `agentsx/cli/commands.py` — 新增 `cmd_compact()`

```python
def cmd_compact(
    store: SessionStore,
    session_id: str,
    messages: list[AgentMessage],
    force: bool = False,
) -> tuple[str, int]:
    """Trigger manual context compaction.

    Args:
        store: SessionStore instance.
        session_id: Current session ID.
        messages: Current conversation messages (will be replaced on success).
        force: If True, skip should_compact() check.

    Returns:
        (status_message, new_message_count) or (error_message, unchanged_count).
    """
    from agentsx.context.compaction import compact_messages, should_compact

    if not force and not should_compact(messages):
        return (
            f"No compaction needed ({len(messages)} messages). "
            f"Use /compact force to override.",
            len(messages),
        )

    old_count = len(messages)
    compacted = compact_messages(messages)
    new_count = len(compacted)

    if new_count >= old_count:
        return "No messages could be compacted.", old_count

    # Record compaction entry
    replaced_ids = [m.id for m in messages[:old_count - new_count + 1]]
    summary = compacted[1].content if len(compacted) > 1 else "Context compacted"
    store.append_compaction_entry(
        session_id,
        replaces_ids=replaced_ids,
        summary=summary,
    )

    # Replace in-memory messages
    messages.clear()
    messages.extend(compacted)

    return (
        f"Compacted: {old_count} → {new_count} messages "
        f"(saved {old_count - new_count})",
        new_count,
    )
```

#### `agentsx/cli/repl.py` — handle_command() 增加 /compact 分支

```python
if command == "/compact":
    force = len(parts) >= 2 and parts[1].lower() == "force"
    msg, new_count = commands.cmd_compact(
        store, session_id, messages, force=force
    )
    console.print(msg)
    return None, model_name
```

#### `agentsx/cli/commands.py` — cmd_help() 添加说明

```
"  /compact [force]            Manually compact context\n"
```

### 测试

CLI 命令无需自动化测试（已有 `/help` 等命令的测试模式）。手动验证即可。

---

## 优化项 4：Session Resume 回放

### 现状

`get_messages()` 只读 `messages.jsonl`，不加载 `compaction.jsonl`。恢复的会话如果有压缩记录，消息列表不完整。

### 方案

在 `get_messages()` 中加载 `compaction.jsonl`，调用 `replay_messages()` 替换已压缩区域。

### 关键变化

#### `agentsx/session/store.py` — `get_messages()` 增加回放逻辑

```python
def get_messages(self, session_id: str) -> list[AgentMessage]:
    """Load all messages for a session, applying compaction replay.

    Uses memory cache when available; falls back to disk read.
    If compaction.jsonl exists, replays compacted regions.
    """
    if session_id in self._message_cache:
        self._message_cache.move_to_end(session_id)
        return list(self._message_cache[session_id])

    path = self._session_dir(session_id) / "messages.jsonl"
    if not path.is_file():
        return []

    messages: list[AgentMessage] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                messages.append(_deserialize_message(json.loads(stripped)))

    # Apply compaction replay
    compaction_path = self._session_dir(session_id) / "compaction.jsonl"
    if compaction_path.is_file():
        from agentsx.context.compaction_entry import (
            load_compaction_entries,
            replay_messages,
        )
        entries = load_compaction_entries(compaction_path)
        messages = replay_messages(messages, entries)

    # Populate cache
    self._message_cache[session_id] = messages
    self._evict_cache()
    return messages
```

### 测试

新增 1 个集成测试：
- `test_get_messages_replays_compaction` — 写入 messages.jsonl + compaction.jsonl，验证 get_messages() 返回回放后的消息列表

---

## 实施顺序

1. **Transport 集成**（最大变更，核心）
2. **RetryEvent 产出**（小变更，依赖 Transport）
3. **Compaction CLI**（小变更，独立）
4. **Session Resume 回放**（小变更，独立）

每项独立可测试，全部合并后一次提交。
