# AgentsX 架构与技术方案

**适用范围**: 代码层架构解析（2026-07-31 快照）
**配套文档**: [官方教程](tutorial.md)（面向使用）、[多项目对比分析](harness-comparative-analysis.md)（设计溯源）

---

## 1. 项目定位

AgentsX 是一个轻量级 AI Agent 运行时框架（Agent Harness），以 **ReAct 循环**（Think → Act → Observe → Repeat）为核心，在 Python 3.10+ 上实现，强调：干净、高效、可扩展、高可用。

- **纯异步**：所有 I/O 均为 `async def`，CLI 使用 `asyncio.run()`。
- **零 Provider Sgit DK 依赖**：通过 httpx 直接调用 HTTP 流式接口，Provider 官方 SDK 为可选 extras。
- **数据驱动配置**：Provider 定义存于 TOML catalog 而非代码；全部配置走 `AGENTSX_*` 环境变量。

---

## 2. 总体架构

分层依赖关系（高层依赖低层，禁止反向）：

```
                        ┌──────────────────────────────┐
                        │         CLI (typer)          │
                        │  chat / run / slash 命令     │
                        └──────────────┬───────────────┘
                                       │
          ┌────────────────────────────┼────────────────────────────┐
          │                            v                            │
          │              ┌──────────────────────────┐              │
          │              │    agent (运行层)        │              │
          │              │ loop / harness / subagent│              │
          │              │ orchestrator            │              │
          │              └──────┬─────────┬─────────┘              │
          │                     │         │                        │
          │     ┌───────────────┼─────┬───┴──────────┐             │
          │     v               v     v              v             │
          │  provider        tools  security       extensions      │
          │  (LLM 抽象)      (工具)  (安全策略)     (观察者/拦截器)  │
          │     │                                             │     │
          │     v                                             v     │
          │  context (上下文压缩/轨迹) ◄──── session (会话持久化)    │
          │                                                     │
          │  workspace (工作区) / discovery (命令/技能发现)        │
          └───────────────────────────────────────────────────────┘
                                       │
                                       v
                            protocol (消息/事件/错误 数据契约)
```

模块总览：

| 模块 | 职责 | 关键文件 |
| ------ | ------ | ---------- |
| `protocol/` | 数据契约：消息、事件、错误分级 | `messages.py`, `events.py`, `errors.py` |
| `provider/` | LLM 提供商抽象（Provider/Transport 双层） | `abc.py`, `factory.py`, `transport.py`, `profile.py`, `catalog.py` |
| `agent/` | ReAct 循环、有状态 Harness、子代理 | `loop.py`, `harness.py`, `agent.py`, `subagent.py` |
| `tools/` | 工具注册表、`@tool()` 装饰器、内置工具 | `__init__.py`, `builtin/` |
| `security/` | 多层安全：策略、路径/命令守卫、资源限制 | `policy.py`, `path_guard.py`, `command_guard.py`, `resource_limits.py` |
| `context/` | 上下文压缩、轨迹跟踪、工具输出剪枝 | `compaction.py`, `trajectory.py`, `tool_pruner.py` |
| `session/` | 会话持久化（JSONL 文件树 / SQLite+FTS5） | `store.py`, `sqlite_store.py`, `snapshot.py` |
| `extensions/` | 扩展 API（观察者 + 拦截器）、多源发现 | `api.py`, `discovery.py` |
| `workspace/` | 工作区感知、git 状态、文件树索引 | `manager.py`, `git.py`, `file_tree.py`, `context_profile.py` |
| `discovery/` | 基于 frontmatter 的命令/技能发现 | `loader.py`, `models.py` |
| `cli/` | 交互式 REPL、slash 命令 | `main.py`, `repl.py`, `commands.py` |
| `config.py` | Pydantic Settings（`AGENTSX_*`） | — |
| `bootstrap.py` | Windows UTF-8 控制台引导 | — |

---

## 3. 核心数据流：ReAct 循环

`run_agent_loop()`（`agent/loop.py:230`）是**纯异步生成器**，是运行时唯一的入口。每轮迭代：

```
 while step < max_steps:
   1. 上下文压缩检查 (should_compact → compact_messages_with_pruning)
   2. yield TurnStartEvent
   3. emit on_loop_start (扩展)
   4. yield ModelRequestEvent → emit on_model_request
   5. provider.stream_with_retry(messages)          # 带指数退避重试
      ├─ TextStreamEvent      → yield TextDeltaEvent / ModelResponseEvent(delta)
      ├─ ToolCallStreamEvent  → 收集为工具调用
      └─ RetryEvent           → 透传 (重试/退避通知)
   6. yield ModelResponseEvent(final)，追加 ASSISTANT 消息
   7. 若无工具调用 → TurnEndEvent(had_tool_calls=False)，循环结束
   8. 逐个执行工具调用:
      ├─ emit on_tool_call
      ├─ 拦截器 pre_tool_call (可 suppress)
      ├─ ExecutionPolicy.evaluate → ALLOW/PROMPT/FORBIDDEN
      ├─ ToolRegistry.call → ToolResult (带输出截断)
      ├─ 拦截器 post_tool_call (可修改结果)
      ├─ emit on_tool_result
      ├─ yield ToolExecutionEvent，追加 TOOL 消息
   9. emit on_loop_end；消费 steer_queue (中断改道)
```

**关键机制**：

- **中断改道（Steer Queue）**：`run_agent_loop` 接受一个可变 `deque`（`loop.py:241`），循环中推送的内容会在下一轮作为 USER 消息注入，实现不打断当前工具执行的打断-改道。`AgentHarness` 在 `_run_loop` 期间将其传入（`harness.py:275`）。
- **Follow-up 队列**：`AgentHarness.prompt()` 在主循环结束后排空 follow-up 队列，每项触发一次新的循环（多轮）。
- **逐层超时**：单步超时 `_wrap_step_timeout`（`loop.py:585`，基于 asyncio.Queue + sentinel，消费侧永不被阻塞）；整循环墙钟超时（`timeout` 参数）。
- **上下文溢出自动恢复**：provider 流抛错时 `classify_api_error()` 若判定 `should_compress=True`，自动压缩后重试该步一次（`loop.py:341-353`）。

---

## 4. Protocol 层（数据契约）

- **`AgentMessage`**（`protocol/messages.py:246`）：唯一内部消息表示，`role`/`content`/`content_parts`（多模态）/`tool_calls`/`tool_call_id`/`id`。转换到 Provider 原生格式发生在 I/O 边界（`convert_to_provider()`）。
- **`ContentPart`**（`messages.py:45`）：多模态内容部件，支持文本/图片/音频/视频的 URL 与 base64 工厂方法。
- **`ToolCall` / `ToolResult`**（`messages.py:161/181`）：结构化工具调用与结果；`ToolResultStatus` ∈ {SUCCESS, ERROR, BLOCKED}。
- **`Decision`**（`messages.py:287`）：ALLOW / PROMPT / FORBIDDEN 三态安全决策（Codex 风格）。
- **事件体系**（`protocol/events.py`）：15 种 `AgentEvent` 联合类型 + `StreamEvent`（Text/ToolCall）。消费者用 `isinstance()` 分发。
- **错误体系**（`protocol/errors.py`）：`AgentsXError` 基类 → `ProviderError`/`ToolError`/`PolicyError`/`SessionError`/`RetryExhaustedError`。`is_retryable` 判定 429/5xx/网络错误。

### 错误分级与智能恢复

`classify_api_error()`（`errors.py:161`）按优先级流水线分类：

```
① thinking signature 不匹配 → 建议 fallback
② 上下文溢出 (marker 扫描)   → 建议重试 + 压缩
③ HTTP 状态码 (401/402/429/403/5xx)
④ 网络启发式 (connection/timeout/ssl/...)
⑤ 兜底 UNKNOWN (可重试)
```

产出 `ClassifiedError{FailoverReason, RecoveryAction{should_retry/compress/fallback, delay, user_hint}}`，驱动 agent loop 的智能恢复（自动压缩、退避重试）。

---

## 5. Provider 层（LLM 抽象）

### 5.1 双层架构：Provider / Transport

| 层 | 职责 | 关键抽象 |
|----|------|----------|
| **Provider**（`provider/abc.py:37`） | 凭据解析、HTTP 客户端、重试编排、`stream()` 流式、`format_messages()` | `Provider` ABC + `Model` dataclass |
| **Transport**（`provider/transport.py:28`） | **纯格式转换**：`format_messages()` / `build_kwargs()` / `parse_stream()` | `ProviderTransport` ABC |

- `OpenAITransport` / `AnthropicTransport`：将 `AgentMessage` 列表转为各 Provider 原生消息，构建请求 kwargs，并把原始 SSE 流解析为 `StreamEvent`（OpenAI `choices[].delta.tool_calls` 增量累积；Anthropic `content_block_start/delta/stop` 累积 `input_json_delta`）。
- 转换函数集中在 `provider/converters.py`：`message_to_openai` / `message_to_anthropic`（TOOL 消息 → OpenAI `role=tool`、Anthropic `tool_result`，多模态 content parts 分 Provider 拼装）。

### 5.2 Provider 实现

- `OpenAIProvider`、`AnthropicProvider`：各自持有对应 Transport，经 httpx `client.stream()` 调用，非 200 抛 `ProviderError(status_code)`。
- `GenericProvider`（`generic.py:29`）：复用 `OpenAITransport`，只需配置 base URL + API key，可覆盖任何 OpenAI 兼容端点；注册了 8 个名称（gemini/deepseek/groq/openrouter/ollama/vllm/sglang/qwen/custom）。

### 5.3 注册与创建

- **注册**：`register_provider(name, cls)` → `_PROVIDER_REGISTRY`（`registry.py`）。
- **工厂解析顺序**（`factory.py:create_provider`）：
  1. catalog 查表（`data/catalog.toml` + `~/.agentsx/catalog.toml` 合并）
  2. slash 记法 `gemini/gemini-2.0-flash` → provider 提示
  3. `resolve_provider_name`（别名/前缀匹配）
  4. 遍历已注册 Provider（前缀/名称匹配）
  5. 找不到 → `ProviderError`
- **配置回退**：`_resolve_provider_kwargs` 依 profile 的 `env_api_key`/`env_api_base` 从 settings 回退 api_key/api_base。

### 5.4 数据驱动目录（catalog.toml）

`provider/data/catalog.toml` 定义 9 家 Provider（OpenAI、Anthropic、Gemini、DeepSeek、Groq、OpenRouter、Ollama、vLLM、SGLang、Qwen）+ 各自模型与 context_window。用户可用 `~/.agentsx/catalog.toml` 覆盖/扩展。新增模型只需改 TOML。

### 5.5 高可用：重试

- `stream_with_retry`（`abc.py:83`）：指数退避 + 抖动（`base * 2^attempt`，封顶 10s），仅对可重试错误（429/5xx/网络）重试；不可重试错误直接抛；超限抛 `RetryExhaustedError`。重试时 yield `RetryEvent` 供前端展示。
- `retry_async` 装饰器（`retry.py`）：通用异步重试工具。

---

## 6. 工具系统

### 6.1 核心抽象

- **`@tool()` 装饰器**（`tools/__init__.py:239`）：函数 → `ToolSpec`，自动从签名生成 JSON Schema（`_json_schema`，支持 `X | Y`、`Optional`、`Literal`、`Enum`、`list[]`/`dict[]` 泛型）。
- **`ToolSpec`**：name / description / fn / parameters / check_fn（条件可见性）/ toolset；`to_openai_format()` / `to_anthropic_format()`。
- **`ToolRegistry`**：注册、按名调用（返回结构化 `ToolResult`）、**toolset 过滤**（启用/禁用某类工具，如仅 `read`）。

### 6.2 风险分级（toolset）

| Toolset | 风险 | 内置工具 | 默认策略 |
| --------- | ------ | ---------- | ---------- |
| `read` | 只读 | `tool_file_read` / `tool_file_glob` / `tool_file_grep` | ALLOW |
| `write` | 变更 | `tool_file_write` / `tool_file_edit` | PROMPT |
| `exec` | 高危 | `tool_bash`（`asyncio.create_subprocess_shell`，可超时 kill） | PROMPT |
| `web` | 只读 | `tool_web_fetch` / `tool_web_search`（DuckDuckGo HTML 抓取，无三方依赖） | ALLOW |
| `orchestration` | 委派 | `spawn_agent`（经全局 `Orchestrator` 单例，深度/并发受限） | — |
| `mcp`（无 toolset） | 外部 | `tool_mcp_call`（MCP over stdio，JSON-RPC 2.0） | — |

`ALL_TOOLS`（`tools/builtin/__init__.py:31`）导出全部 10 个工具。

---

## 7. 安全层

### 7.1 ExecutionPolicy（运行时主闸）

`ExecutionPolicy.evaluate()`（`security/policy.py:62`）四段式决策管线：

```
① Path guard（allowed_dirs 内嵌检查，5 个文件工具）→ FORBIDDEN
② SavedRulesStore（用户持久化 allow/deny，最高优先）→ 命中即返回
③ 内置 fnmatch 规则，匹配 "tool_name:{json_args}"（args JSON 排序）→ 首条命中
④ 默认决策（默认 PROMPT）
```

- 默认策略（`ExecutionPolicy.default()`）：只读/网络工具 ALLOW，写/编辑/shell PROMPT。
- **未接入点**：`AGENTSX_POLICY_DEFAULT` 目前未被 `ExecutionPolicy` 构造读取（`config.py:59`）。

### 7.2 PathGuard（路径守卫）

`path_guard.py:check()` 校验管线：realpath 解析 → 符号链接逐组件扫描 → **junction/reparse 点检测**（`st_reparse_tag`）→ **硬链接逃逸检测**（inode 越界）→ 工作区边界 `is_subpath` → `..` 穿越模式兜底。

> 注意：PathGuard 与 CommandGuard 目前是**独立组件**，尚未接入工具执行链（`tool_bash` 直接 `create_subprocess_shell`，未先经 CommandGuard 过滤）。属于待落地的安全强化项。

### 7.3 CommandGuard（命令守卫）

`command_guard.py:check()`：注入正则（管道到危险命令、反引号/`$()` 子 shell、`echo|printf|bash` 等）+ 禁止 fnmatch（`rm -rf /`、fork bomb、`mkfs.*`、`dd of=/dev/*` 等）+ 警告模式（`rm -rf*`、`sudo`、`bash -c` 等）→ SAFE/WARNING/FORBIDDEN。

### 7.4 ResourceLimits（资源限制）

`resource_limits.py`：`max_output_chars=50_000`、`max_stderr_chars=5_000`、`max_file_read_lines=10_000`、`max_glob_results=1_000`、`max_grep_matches=500`、`max_history_length=10_000`；`truncate_head_tail` 保留头尾 + 省略计数。agent loop 侧以 `min(max_output, limit)` 作为单次调用输出上限（`loop.py:641-658`）。

### 7.5 SavedRulesStore（持久化规则）

`~/.agentsx/saved_rules.json`，`SavedRule{action, resource, effect, note}` 数组；支持 `add/remove/list/clear/evaluate`，`evaluate` 用 `fnmatch(tool_name, action) && fnmatch(path, resource)`。

---

## 8. 上下文管理

### 8.1 Token 估算（CJK 感知）

`estimate_tokens()`（`context/compaction.py:56`）按 Unicode 分类：CJK 约 1.5 字符/token、拉丁约 4 字符/token、空白按 8 字符/token。

### 8.2 压缩触发与执行

- `should_compact()`：消息数 ≥ 14 且（`max_messages=50` 或 token 预算）超阈值。
- `compact_messages()`：**保留 system + 最近 N 条**，历史压缩为结构化摘要（已完成任务 / 进行中 / 关键决策 / 相关文件），附 **SUMMARY 结束标记**（防止模型把摘要当指令），摘要以 USER 角色消息注入（Provider 兼容性）。
- `compact_messages_with_pruning()`：先 `ToolPruner` 剪枝冗余工具输出，再结构化压缩（**运行时推荐入口**，loop 与 harness 均使用）。
- `ToolPruner`（`tool_pruner.py`）：将超长工具输出替换为单行摘要（bash 退出码/行数、read 字符数、grep 命中数等，按工具分派）。

### 8.3 追加式压缩审计（compaction entry）

`CompactionEntry{replaces_ids, summary, token_estimate}` 追加写入会话目录 `compaction.jsonl`；`replay_messages()` 在读取时把压缩区间重放为 `ASSISTANT` 摘要消息，**不修改**只增日志，保留完整审计链。

### 8.4 轨迹跟踪

`Trajectory`（`context/trajectory.py:45`）：记录 think/tool_call/tool_result/error 事件链，支持 `to_jsonl`/`from_jsonl`，用于调试、重放与上下文感知压缩。

### 8.5 ContextManager（统一门面）

`ContextManager` 聚合压缩/摘要/轨迹，但**运行时代码路径不经过它**——loop/harness 直接调用 `compaction.py`。`ContextSummarizer` 为**统计式摘要**（非 LLM），`max_summary_tokens` 为死配置，属文档与实现偏差项。

---

## 9. 会话管理

### 9.1 SessionBackend 协议

`session/protocol.py` 定义统一接口：create/get/get_messages/append/list_sessions/delete/branch/update_title/append_compaction_entry/close。高层组件（`AgentHarness`）只依赖协议，不依赖具体后端。

### 9.2 JSONL 文件树（默认）

```
~/.agentsx/sessions/<id>/
├── meta.json           # 会话元数据
├── messages.jsonl      # 每行一条 AgentMessage（append-only）
└── compaction.jsonl    # 追加式压缩审计
```

- 零三方依赖、追加 O(1) 写、LRU 内存缓存（默认 10）、延迟时间戳刷盘（避免读改写竞争）、分支 = 拷贝文件 + 新 meta。

### 9.3 SQLite + FTS5（可选）

`SQLiteSessionStore`：`sessions`/`messages`/`compaction_entries` 三表 + FTS5 虚拟表（trigger 同步），WAL 模式、`foreign_keys=ON`；支持跨会话全文检索（`snippet` + rank）、来源标记（cli/telegram/discord）、父-子分支链。工厂 `create_session_store("jsonl"|"sqlite")`。

### 9.4 快照回滚

`SessionSnapshot`（`session/snapshot.py`）：压缩前捕获文件 SHA-256 哈希与原始内容，`rollback()` 恢复，`has_changes()` 比对，作为错误压缩的安全网。

---

## 10. 扩展系统

### 10.1 双模式事件

- **观察者事件**（7 个）：`on_loop_start/end`、`on_model_request/response`、`on_tool_call/result`、`on_error`。
- **拦截器事件**（5 个）：`pre_tool_call`（可 suppress/modify）、`post_tool_call`（可改结果）、`pre_compact`、`session_start/end`。
- **异常隔离**：任何 handler 抛错只记录日志，绝不中断 loop（`extensions/api.py:167-199`）。

### 10.2 多源发现

`discover_extensions()` 合并顺序（后者覆盖前者）：entry_points（`agentsx.extensions`）→ 用户目录 `~/.agentsx/extensions/*.py` → 项目目录 `./.agentsx/extensions/*.py` → 内置 `agentsx/extensions/builtin/`（目录当前为空）。文件插件需暴露 `setup(api)` 可调用对象。

---

## 11. 工作区、发现与子代理

### 11.1 工作区（workspace）

- `WorkspaceManager`：根目录、`get_info()`（git 检测、文件/目录计数）、`is_within()` 路径包含检查。
- `GitWatcher`：分支、修改文件、未跟踪文件（`git rev-parse` + `git diff` + `git ls-files`，5s 超时）。
- `FileTreeIndex`：最大深度 3 的文件树（忽略 `.git/.venv/node_modules` 等）。
- `ContextProfile`：**运行时姿态检测**——检测到任一祖先含 `.git` 且存在源码文件则判为 `CODING`（工具过滤为 read/write/exec/orchestration），否则 `GENERAL`。

### 11.2 命令/技能发现（discovery）

- **frontmatter 解析器**（`loader.py`）：手写解析 `---\nkey: value\n---`（无 YAML 依赖），支持 bool 强转与列表字段。
- `scan_commands()`：扫描 `*.md`，要求 `description`；`scan_skills()`：`<dir>/<skill-name>/SKILL.md` 布局，可带 `references/`。
- 聚合顺序：用户全局 `~/.agentsx/commands` 或 `AGENTSX_DISCOVERY_DIR` → 项目本地 `./.agentsx/commands`，按名称去重（项目覆盖用户）。
- 模型：`DiscoveredCommand{name, description, instructions, arguments, allowed_tools, model}`、`DiscoveredSkill{..., version, trigger_patterns, resource_dir}`。

### 11.3 子代理与编排

- `Orchestrator`（`orchestrator.py`）：全局单例，`max_active=5`、`max_spawn_depth=2`，负责 spawn/记录/超时运行。
- `SubAgentRuntime`（`agent/subagent.py`）：独立 Provider + ToolRegistry + 消息列表；角色 `leaf`（不能委派）vs `orchestrator`（可 spawn 子代，受 `spawn_agent` 限制）；默认只读工具集，`DELEGATE_BLOCKED_TOOLS` 显式封禁 `spawn_agent`。
- `AgentHarness`（`agent/harness.py`）：有状态门面，持有消息历史、事件订阅者、取消状态与两个消息队列；执行委托给纯 `run_agent_loop`。
- `Agent`（`agent/agent.py`）：便捷包装，懒创建 harness，跨 `run()` 保持历史。

---

## 12. CLI 与配置

### 12.1 CLI（typer）

- `agentsx chat`：prompt_toolkit 交互 + rich 流式输出/工具面板/会话信息表；`--model/--system/--no-tools/--max-steps/--allow-all/--session/--timeout/--workspace/--image/--audio/--video`；支持多模态首条消息。
- `agentsx run "prompt"`：单轮脚本化执行。
- **slash 命令**：`/sessions`、`/session show|switch`、`/new`、`/delete`、`/branch`、`/title`、`/compact [force]`、`/clear`、`/help`、`/exit`。会话切换后从 store 重载消息。

### 12.2 配置（Pydantic Settings）

- `AgentsXSettings`：`AGENTSX_` 前缀环境变量 + 项目根 `.env`，`extra="ignore"`，模块级单例 `settings`，Provider 模块通过 `get_settings()` 运行时取用（允许运行时重配）。
- 主要分组：Model / Agent / Session / Discovery / Security / 各 Provider Key / Tools / 高可用（重试次数、基础退避、loop 超时、最大工具输出）/ Web 工具。

---

## 13. 技术选型与依赖

| 类别 | 选型 | 说明 |
| ------ | ------ | ------ |
| 语言/运行时 | Python 3.10+ | `X \| Y` 联合类型原生支持，无 `from __future__` |
| 依赖管理 | uv | `.venv` 项目本地虚拟环境 |
| 配置 | pydantic v2 + pydantic-settings | 类型强转 + 校验 |
| CLI | typer + prompt_toolkit + rich | 交互式 REPL、流式渲染、表格/面板 |
| HTTP | httpx | 异步流式 SSE 客户端 |
| 数据序列化 | JSON/JSONL/TOML | catalog=TOML、会话=JSONL、frontmatter 手写解析 |
| 校验 | ruff + mypy --strict + pytest | 见 AGENTS.md |
| 前端（预留） | Vite + React + TypeScript | `frontend/` 仅为最小聊天 UI，`/api` 代理到 :8000，后端尚未实现 |

---

## 14. 扩展点速查

| 想做什么 | 怎么做 |
| ---------- | -------- |
| 新增 LLM Provider | 在 `data/catalog.toml` 加条目（或 `~/.agentsx/catalog.toml`），若为 OpenAI 兼容端点则无需写代码 |
| 新增工具 | `@tool(description=..., toolset=...)` 定义函数，加入 `ALL_TOOLS`；JSON Schema 自动生成 |
| 新增工具类别（toolset） | 定义 toolset 常量并在 `ToolRegistry` 启用/禁用 |
| 拦截工具执行 | 注册 `pre_tool_call` / `post_tool_call` 拦截器 |
| 监听生命周期 | `ExtensionAPI.on(EVENT_ON_*)` 注册观察者 |
| 持久化规则 | `SavedRulesStore.add(action, resource, effect)` |
| 自定义会话后端 | 实现 `SessionBackend` Protocol，注册进 `create_session_store` |
| 新增 slash 命令 | 在 `cli/commands.py` 添加 `cmd_*` 并在 `cli/repl.py` 分发 |

---

## 15. 已知设计与实现偏差

以下为文档与实现不一致或待落地的点，供后续工作参考：

1. **PathGuard / CommandGuard 未接入工具执行链**：目前仅 ExecutionPolicy + allowed_dirs + 输出截断在运行时生效；`tool_bash` 未先过 CommandGuard。
2. **`AGENTSX_POLICY_DEFAULT` 未生效**：`ExecutionPolicy` 构造未读取该配置。
3. **`ContextSummarizer` 是统计式而非 LLM 摘要**：docstring 与 `max_summary_tokens` 存在偏差；运行时压缩路径（loop/harness）并不经过 `ContextManager`/`ContextSummarizer`。
4. **`tool_mcp_call` 为同步阻塞**、无 toolset、无超时；其余工具均异步。
5. **grep 剪枝错配**：`ToolPruner` 期望 `tool_file_grep` 输出含 JSON `total_count`，而实际 grep 工具输出为纯文本。
6. **AnthropicProvider 的 `headers` 混入 `build_kwargs`**（`anthropic.py:86`），Transport 边界略被突破。
7. **DeepSeek `max_tokens` 特判**（`generic.py:122-123`）为 Provider 特例硬编码。
8. **`agentsx/security.py` 与 `core/__init__.py` 为向后兼容 shim**（弃用告警），依赖解析优先包。
9. **`AGENTSX_MAX_STEPS`/`AGENTSX_TOOL_TIMEOUT` 等资源限制未全部走环境变量**：`ResourceLimits` 为 dataclass 默认值，无 env 映射。

---

## 16. 与主流框架对比

本节对比 DeerFlow、LangChain/LangGraph、Pi、Tau、Hermes-Agent 五个代表性 Agent 框架，定位 AgentsX 的设计取向与差异点。详细横向分析见[多项目对比分析](harness-comparative-analysis.md)。

### 16.1 总体对比

| 维度 | AgentsX | DeerFlow 2.0 | LangGraph | Pi | Tau | Hermes-Agent |
| ------ | --------- | -------------- | ----------- | ----- | ----- | -------------- |
| 语言 | Python 3.10+ | Python | Python | TypeScript | Python | Python |
| 循环模型 | 纯 async 生成器（ReAct） | SuperAgent 编排（嵌套 Agent） | 图模型（State+Nodes+Edges） | FSM 状态机 | 事件驱动 | 事件驱动 |
| 控制流 | 代码内 `async for` 惰性求值 | 编排器调度子代理 | super-step 静态图执行 | 显式状态转换 | channel + select | 事件总线 |
| 上下文压缩 | CJK-aware 统计式压缩 | 记忆系统 | checkpointer + 记忆 | 分支切换摘要 | Token 预算自动压缩 | LLM 语义压缩器 |
| 工具系统 | 装饰器 + JSON Schema + risk-tier | extensible skills | ToolNode | 内建工具 | 队列化并行 | ToolSpec + 插件 |
| 安全模型 | ExecutionPolicy + Path/Command/Resource | 沙箱 | 外部化（无内建） | bubblewrap 沙箱 | 依赖层 | 依赖层 |
| 持久化 | JSONL + SQLite 双后端 | 记忆存储 | checkpointer | 会话文件 | 会话存储 | 会话存储 |
| 扩展点 | 观察者 + 拦截器 | skills / 子代理 | 节点自定义 | 状态自定义 | 事件订阅 | 插件发现 |
| 依赖 | 零 Provider SDK 依赖 | LangGraph Gateway 兼容 | LangChain 生态 | — | 分层单向依赖 | 中心 ContextManager |

### 16.2 与 DeerFlow 2.0

- **共同点**：均为"harness"路线——不定义业务逻辑，提供 Agent 运行与编排骨架；都支持子代理与长周期任务。
- **差异**：DeerFlow 2.0 是 ground-up rewrite（与 1.x 无共享代码），以 SuperAgent 编排嵌套 sub-agents/memory/sandboxes 为主模型；AgentsX 以单循环 ReAct 生成器为核心，子代理仅作为可选编排。
- **LangGraph 兼容路径**：DeerFlow Gateway 对外暴露 `/api/langgraph/*`（LangGraph 兼容路由），nginx 转发至原生 `/api/*`，从而接入 LangGraph Studio/Server；身份映射为稳定目录 user_id。AgentsX 无此兼容层——协议自有，不承诺 LangGraph 互操作。
- **借鉴方向**：长周期任务的显式编排模型、身份映射策略、沙箱执行。

### 16.3 与 LangChain/LangGraph

- **图模型 vs 生成器**：LangGraph 将 Agent 建模为 State + Nodes + Edges，类 Pregel 消息传递、super-step 执行；同一 super-step 内节点并行，跨 super-step 串行，全部节点 inactive 即终止。AgentsX 用单个 async 生成器表达顺序 ReAct 循环，天然顺序、无并行 super-step 语义。
- **State 处理**：LangGraph 的 State 是共享快照（channel 定义），图在 checkpoint 上可中断/恢复；AgentsX 的 `run_agent_loop()` 不持有状态，消息历史由调用方（Harness）维护，中断通过 Steering 队列注入。
- **生态**：LangGraph 依赖 LangChain 生态（模型、工具、检索），checkpointer 提供持久化；AgentsX 零第三方依赖、Provider 层自有，适合嵌入式轻量场景。
- **借鉴方向**：中断/恢复（interrupt/resume）与 checkpointer 机制，用于增强 AgentsX 的 Steering 与持久化能力。

### 16.4 与 Pi

- **FSM vs 生成器**：Pi 用显式状态机（UserInput → ContextLoad → LLMRequest → ToolExecute → ContextUpdate → Loop/Exit），每个状态有 entry/exit 函数，转换路径确定、可追溯；AgentsX 的状态隐含在生成器迭代中，控制流是代码而非状态表。
- **沙箱**：Pi 通过 bubblewrap 实现 Linux 级沙箱隔离；AgentsX 目前的安全侧重 ExecutionPolicy + 工具级防护，无进程级沙箱。
- **优势权衡**：Pi 的确定性可调试性好于生成器，但中途打断不如 AgentsX 的 Steering 队列灵活（Pi 需通过状态转换实现）。

### 16.5 与 Tau

- **并发模型**：Tau 是事件驱动，流式 LLM 响应经 channel + select 分发，工具执行队列化可并行；AgentsX 使用单线程 async，工具并发依赖调用方编排。
- **压缩时机**：Tau 由 token 预算阈值触发自动压缩；AgentsX 的 `ContextSummarizer` 同为阈值驱动（见 §15 偏差第 3 条）。
- **分层**：Tau 为 `tau_ai → tau_agent → tau_coding` 严格单向分层；AgentsX 为 CLI → agent → provider/tools/security/extensions 的分层，依赖方向同样单向。

### 16.6 与 Hermes-Agent

- **解耦方式**：Hermes-Agent 用中心 `ContextManager` + 事件总线解耦各组件，每步发射 `on_tool_start/on_tool_result/on_error` 事件；AgentsX 用观察者/拦截器扩展（§10），核心循环不依赖事件总线，开销更低、执行流更易追踪。
- **工具定义**：Hermes-Agent 用 ToolSpec + 插件系统发现；AgentsX 用 `@tool()` 装饰器自动生成 JSON Schema，ToolRegistry 管理启停。
- **压缩器**：Hermes-Agent 的 `ContextCompressor` 支持可选 LLM 语义摘要；AgentsX 的 `ContextSummarizer` 为统计式（见 §15 偏差第 3 条），语义摘要是后续方向。
