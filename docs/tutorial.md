# AgentsX 官方教程

AgentsX 是一个轻量级的 AI Agent 运行时框架：以 ReAct（Think → Act → Observe → Repeat）循环为核心，提供多 Provider 抽象、按风险分层的工具系统、多层安全策略、上下文压缩、会话管理、扩展 API 与交互式 CLI。

本文档面向使用者与二次开发者，覆盖从安装、CLI、Python API 到各子系统（Provider、工具、安全、上下文、会话、扩展、子代理、工作区）的完整使用方式。

## 目录

- [1. 特性总览](#1-特性总览)
- [2. 安装与配置](#2-安装与配置)
- [3. CLI 快速开始](#3-cli-快速开始)
- [4. Python API](#4-python-api)
- [5. Provider 体系](#5-provider-体系)
- [6. 工具系统](#6-工具系统)
- [7. 安全模型](#7-安全模型)
- [8. 上下文管理](#8-上下文管理)
- [9. 会话管理](#9-会话管理)
- [10. 扩展系统](#10-扩展系统)
- [11. 子代理与编排](#11-子代理与编排)
- [12. 工作区与技能发现](#12-工作区与技能发现)
- [13. 事件与错误处理](#13-事件与错误处理)
- [14. 配置参考](#14-配置参考)
- [15. 开发与验证](#15-开发与验证)

---

## 1. 特性总览

- **ReAct 智能体循环**：`run_agent_loop()` 为纯异步生成器，驱动"思考 → 行动 → 观察 → 重复"，`max_steps` 可配置，支持 `timeout` 与中断改道（steer queue）。
- **多 Provider 抽象**：内置 10 家提供商（OpenAI、Anthropic、Gemini、DeepSeek、Groq、OpenRouter、Ollama、vLLM、SGLang、Qwen/DashScope），Provider/Transport 双层抽象，`GenericProvider` 可接入任意 OpenAI 兼容端点。
- **内置工具系统**：`@tool()` 装饰器自动生成 JSON Schema；按风险分层组织（read / write / exec / web / orchestration / mcp）。
- **多层安全**：ExecutionPolicy（ALLOW/PROMPT/FORBIDDEN）+ PathGuard（路径逃逸检测）+ CommandGuard（危险命令/注入检测）+ ResourceLimits（输出截断）。
- **上下文管理**：自动上下文压缩（基于 token 计数，CJK 感知估算），可选 LLM 摘要，追加式压缩审计轨迹。
- **会话管理**：默认 JSONL 文件树，可选 SQLite + FTS5 全文检索；`SessionBackend` 协议统一接口，支持分支（branch）与快照回滚。
- **扩展 API**：观察者 + 拦截器模式，异常隔离，支持 entry-points / 目录 / 内置多源自动发现。
- **交互式 CLI**：`agentsx chat`（prompt_toolkit + rich 流式输出、工具面板、slash 命令）与 `agentsx run`（单轮脚本化）。

---

## 2. 安装与配置

### 2.1 环境要求

- Python 3.10 及以上
- [uv](https://github.com/astral-sh/uv)（推荐，项目使用 uv 管理依赖与虚拟环境）

### 2.2 安装

```bash
git clone <repo-url>
cd agentsx
uv sync

# 可选：安装 Provider 官方 SDK 依赖
uv sync --extra openai      # OpenAI
uv sync --extra anthropic   # Anthropic
```

虚拟环境位于项目根 `.venv`。Windows 下激活：

```bat
.venv\Scripts\activate.bat
```

### 2.3 配置

复制模板并填入 API Key：

```bash
cp .env.example .env
```

所有配置均通过 `AGENTSX_*` 环境变量或项目根 `.env` 文件读取（Pydantic Settings）。主要配置项：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AGENTSX_MODEL_NAME` | `gpt-4o` | 默认模型标识 |
| `AGENTSX_API_KEY` | 空 | 默认 API Key（无 Provider 专用 Key 时的兜底） |
| `AGENTSX_API_BASE` | 空 | 默认 API Base URL |
| `AGENTSX_MAX_STEPS` | `25` | 单轮最多工具调用迭代次数（1–200） |
| `AGENTSX_SYSTEM_PROMPT` | `You are a helpful AI assistant.` | 默认系统提示词 |
| `AGENTSX_SESSION_DIR` | 空（→ `~/.agentsx/sessions/`） | 会话存储目录 |
| `AGENTSX_POLICY_DEFAULT` | `prompt` | 默认策略：`allow` / `prompt` / `forbidden` |
| `AGENTSX_TOOL_TIMEOUT` | `30` | 工具执行超时（秒） |
| `AGENTSX_PROVIDER_RETRY_COUNT` | `3` | Provider 调用重试次数 |
| `AGENTSX_PROVIDER_RETRY_BASE_DELAY` | `1.0` | 指数退避基础延迟（秒） |
| `AGENTSX_LOOP_TIMEOUT` | `0` | 整个 agent loop 的墙钟超时（0 = 禁用） |
| `AGENTSX_MAX_TOOL_OUTPUT` | `50000` | 单个工具返回的最大字符数（0 = 不限） |
| `AGENTSX_WEB_SEARCH_URL` | `https://html.duckduckgo.com/html/` | Web 搜索端点 |
| `AGENTSX_WEB_USER_AGENT` | AgentsX UA | HTTP 请求 User-Agent |

Provider 专用变量见 [14. 配置参考](#14-配置参考) 与 [5. Provider 体系](#5-provider-体系)。

---

## 3. CLI 快速开始

### 3.1 交互式对话

```bash
# 交互式聊天（默认模型取 AGENTSX_MODEL_NAME）
agentsx chat

# 指定模型
agentsx chat --model claude-sonnet-4-20250514

# 禁用全部工具
agentsx chat --no-tools

# 跳过安全确认（ALLOW 所有工具）
agentsx chat --allow-all

# 将文件工具限制在工作区内
agentsx chat --workspace /path/to/project

# 自定义系统提示词
agentsx chat --system "You are a coding assistant."

# 恢复指定会话
agentsx chat --session <session-id>

# 限制整个循环的墙钟超时（秒）
agentsx chat --timeout 120
```

### 3.2 单轮执行

```bash
agentsx run "Summarize README.md"
agentsx run "Summarize README.md" --model gpt-4o-mini --max-steps 10
```

适合脚本化与管道输出。

### 3.3 CLI 选项

| 选项 | 命令 | 说明 |
|------|------|------|
| `--model` / `-m` | chat, run | 模型标识（默认取 `AGENTSX_MODEL_NAME`） |
| `--system` / `-s` | chat | 系统提示词覆盖 |
| `--no-tools` | chat, run | 禁用全部内置工具 |
| `--max-steps` | chat, run | 工具调用迭代上限 |
| `--allow-all` | chat, run | 跳过策略检查（ALLOW 所有工具） |
| `--timeout` | chat, run | Agent 循环墙钟超时（秒，0 = 禁用） |
| `--session` | chat | 恢复指定会话 ID（空则新建） |
| `--workspace` / `-w` | chat | 将文件工具限制到该目录 |

### 3.4 Slash 命令

`agentsx chat` 中输入 `/` 开头命令：

| 命令 | 说明 |
|------|------|
| `/sessions` | 列出所有会话 |
| `/session show <id>` | 查看会话详情 |
| `/session switch <id>` | 切换到指定会话 |
| `/new [title]` | 新建会话并切换 |
| `/delete <id>` | 删除会话（不能删除当前活动会话） |
| `/branch <id> [title]` | 从指定会话分支并切换 |
| `/title <name>` | 重命名当前会话 |
| `/compact [force]` | 手动触发上下文压缩（`force` 跳过阈值检查） |
| `/clear` | 清空对话历史 |
| `/help` | 显示命令帮助 |
| `/exit`、`/quit` | 退出聊天 |

---

## 4. Python API

### 4.1 最小示例：直接驱动 Agent 循环

```python
import asyncio
from agentsx.agent.loop import run_agent_loop
from agentsx.protocol.messages import AgentMessage, MessageRole
from agentsx.provider import create_provider
from agentsx.security import ExecutionPolicy
from agentsx.tools import ToolRegistry
from agentsx.tools.builtin import ALL_TOOLS

async def main():
    provider = create_provider(model_name="gpt-4o")
    tools = ToolRegistry()
    tools.register_all(*ALL_TOOLS)

    messages = [
        AgentMessage(role=MessageRole.SYSTEM, content="You are a helpful assistant."),
        AgentMessage(role=MessageRole.USER, content="Read README.md and summarize it."),
    ]

    async for event in run_agent_loop(
        provider,
        messages,
        max_steps=10,
        tools=tools,
        policy=ExecutionPolicy.default(),
    ):
        print(event)

asyncio.run(main())
```

### 4.2 高层 `Agent` 类（多轮对话）

```python
from agentsx.agent import Agent

async def main():
    agent = Agent(model_name="gpt-4o")

    async for event in agent.run("What is Python?"):
        pass
    async for event in agent.run("And Rust?"):
        pass  # 会记住上一轮对话

    agent.clear_history()  # 清空历史，保留系统提示词

asyncio.run(main())
```

### 4.3 `run_agent_loop` 签名

```python
async def run_agent_loop(
    provider: Provider,                 # LLM Provider 实例
    messages: list[AgentMessage],       # 对话历史（可能被就地压缩）
    max_steps: int | None = None,       # 工具调用迭代上限，None → AGENTSX_MAX_STEPS
    tools: ToolRegistry | None = None,  # 工具注册表
    policy: ExecutionPolicy | None = None,  # 安全策略
    extensions: ExtensionAPI | None = None, # 扩展钩子
    timeout: float = 0,                 # 整个循环墙钟超时（0 = 禁用）
    compact: bool = True,               # 是否自动上下文压缩
    compact_max_tokens: int = 0,        # 触发压缩的 token 预算（0 = 仅按消息数）
    compact_max_messages: int = 50,     # 触发压缩的最大消息数
    steer_queue: deque[str] | None = None,  # 中断改道队列
) -> AsyncIterator[AgentEvent]:
```

产出的事件类型见 [13. 事件与错误处理](#13-事件与错误处理)。

---

## 5. Provider 体系

### 5.1 内置 Provider 目录

Provider 与模型定义集中在 `agentsx/provider/data/catalog.toml`，用户可在 `~/.agentsx/catalog.toml` 覆盖合并。

| Provider | Base URL | 默认模型 | 备注 |
|----------|----------|----------|------|
| openai | `https://api.openai.com/v1` | `gpt-4o` | gpt-4o / gpt-4o-mini / o1 / o3-mini |
| anthropic | `https://api.anthropic.com/v1` | `claude-sonnet-4-20250514` | 自动附加 `anthropic-version: 2023-06-01` 头 |
| gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.0-flash` | 1M 上下文，OpenAI 兼容格式 |
| deepseek | `https://api.deepseek.com/v1` | `deepseek-chat` | 1M 上下文 |
| groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` | |
| openrouter | `https://openrouter.ai/api/v1` | 空 | 需显式指定模型 |
| ollama | `http://localhost:11434/v1` | `llama3` | 本地，无需 API Key |
| vllm | `http://localhost:8000/v1` | 空 | 模型由服务端动态加载 |
| sglang | `http://localhost:30000/v1` | 空 | 模型由服务端动态加载 |
| qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` | 阿里云百炼 DashScope |

### 5.2 模型解析顺序

`create_provider(model_name)` 的解析链：

1. **目录查找**：`catalog.toml`（内置 + 用户覆盖）命中即注册 profile 并创建 Provider。
2. **Slash 记法**：`"gemini/gemini-2.0-flash"` → 斜杠前为 provider 提示。
3. **别名/前缀**：通过 profile 的 `model_prefix`（如 `gpt-`、`claude-`）解析。
4. **注册表遍历**：按前缀或名称依次尝试已注册 Provider。

```python
from agentsx.provider import create_provider

p = create_provider("gpt-4o")
p = create_provider("gemini/gemini-2.0-flash")
p = create_provider("deepseek/deepseek-chat")
p = create_provider("anthropic/claude-sonnet-4-20250514")
```

### 5.3 自定义 Provider

实现 `Provider` 抽象类（`stream()` + `format_messages()`），再注册到全局注册表：

```python
from agentsx.provider import Provider, Model, register_provider

class MyProvider(Provider):
    def __init__(self, model: Model, api_key: str = "", **kwargs) -> None:
        super().__init__(model, api_key=api_key, **kwargs)

    async def stream(self, messages, **kwargs):
        ...

    def format_messages(self, messages, **kwargs):
        ...

register_provider("my_provider", MyProvider)
```

### 5.4 任意 OpenAI 兼容端点

任何遵循 OpenAI 聊天补全协议的服务（本地推理、代理网关等）都可直接接入：

```python
provider = create_provider("my-custom-model", api_base="http://localhost:8000/v1")
```

未在注册表中命中的目录条目会自动回退到 `GenericProvider`。

---

## 6. 工具系统

### 6.1 定义工具：`@tool()`

```python
from agentsx.tools import tool

@tool(description="Compute the sum of two integers")
def tool_add(a: int, b: int) -> int:
    """Return a + b."""
    return a + b
```

装饰器会根据函数签名自动生成 JSON Schema，并包装为 `ToolSpec`。

### 6.2 注册与调用

```python
from agentsx.tools import ToolRegistry, tool

registry = ToolRegistry()
registry.register(tool_add)
registry.register_all(*ALL_TOOLS)   # 注册全部内置工具

# 直接调用
result = await registry.call("tool_add", a=1, b=2)
print(result.status, result.content)
```

`ToolRegistry` 关键方法：

- `register(tool)` / `register_all(*tools)`
- `call(name, **kwargs) -> ToolResult`
- `list_tools()` / `list_toolsets()`
- `enable_toolset(name)` / `disable_toolset(name)` / `enable_all_toolsets()`

### 6.3 内置工具

内置工具按风险分层组织，统一由 `agentsx.tools.builtin.ALL_TOOLS` 导出：

| 风险层 | 工具 | 说明 |
|--------|------|------|
| read | `tool_file_read` | 读取文件（支持 offset/limit） |
| read | `tool_file_glob` | 按模式匹配文件路径 |
| read | `tool_file_grep` | 内容正则搜索 |
| write | `tool_file_write` | 写入/创建文件 |
| write | `tool_file_edit` | 精确字符串替换编辑 |
| exec | `tool_bash` | 异步执行 shell 命令（带超时） |
| web | `tool_web_fetch` | 抓取 URL（text / html） |
| web | `tool_web_search` | 网页搜索（默认 DuckDuckGo HTML） |
| orchestration | `spawn_agent` | 派生子代理执行任务 |
| mcp | `tool_mcp_call` | 调用外部 MCP 服务器工具 |

### 6.4 工具集（Toolset）

工具可按风险分组，实现按需启用/禁用。例如只暴露只读工具给模型：

```python
registry = ToolRegistry()
registry.register_all(*ALL_TOOLS)
registry.enable_toolset("read")       # 只暴露 read 工具集
registry.disable_toolset("write")
```

预定义工具集：`read`、`write`、`exec`、`web`、`orchestration`、`vision`。

---

## 7. 安全模型

安全是分层叠加的，任何一层拦截都会阻止执行。

### 7.1 ExecutionPolicy（策略门控）

规则为 `Rule(pattern, decision)`，使用 fnmatch 匹配 `"tool_name:{json_args}"` 字符串，三级决策 `ALLOW` / `PROMPT` / `FORBIDDEN`：

```python
from agentsx.protocol.messages import Decision
from agentsx.security import ExecutionPolicy, Rule

policy = ExecutionPolicy(
    rules=[
        Rule("tool_file_read:{path:*}", Decision.ALLOW),
        Rule("tool_bash:{command:*}", Decision.PROMPT),
        Rule("tool_file_write:{path:*}", Decision.FORBIDDEN),
    ],
    default_decision=Decision.PROMPT,  # 未命中规则时默认行为
)
```

内置工厂方法：

```python
policy = ExecutionPolicy.default()                # 只读工具 ALLOW，变更工具 PROMPT
policy = ExecutionPolicy(default_decision=Decision.ALLOW)  # 全部放行（等价 --allow-all）
```

`--workspace` 模式会将文件工具的允许范围限制在指定目录内。

### 7.2 PathGuard（路径防护）

校验文件路径不越出工作区边界，检测 `..` 遍历、符号链接（symlink）、junction 与硬链接逃逸（含 Windows reparse point）：

```python
from pathlib import Path
from agentsx.security import PathGuard

guard = PathGuard(workspace=Path("/path/to/project"))
result = guard.check("/path/to/project/README.md")
if result.is_safe:
    ...
```

### 7.3 CommandGuard（命令防护）

检测危险 shell 命令（如 `rm -rf /`、`mkfs`、`dd`、fork 炸弹）与 shell 注入模式，输出威胁等级 `ThreatLevel`（SAFE / WARNING / DANGEROUS / FORBIDDEN）：

```python
from agentsx.security import CommandGuard

guard = CommandGuard()
result = guard.check("rm -rf /")
print(result.threat_level)  # FORBIDDEN
```

### 7.4 ResourceLimits（资源限制）

防止工具输出淹没上下文。默认值：

| 限制 | 默认 |
|------|------|
| `max_output_chars` | 50,000 |
| `max_file_read_lines` | 10,000 |
| `max_glob_results` | 1,000 |
| `max_grep_matches` | 500 |
| `truncate_head` | 3,000 |
| `truncate_tail` | 1,000 |

截断保留头尾，中间以省略计数说明（对 LLM 上下文更友好）：

```python
from agentsx.security import get_limits

limits = get_limits()
text = limits.truncate_head_tail(long_output)
```

### 7.5 持久化规则

用户对 PROMPT 决策的选择可持久化到 `~/.agentsx/saved_rules.json`（`SavedRulesStore`），避免每次重复确认。

---

## 8. 上下文管理

### 8.1 自动压缩

当消息数超过 `compact_max_messages`（默认 50）或 token 数超过预算时，`run_agent_loop` 自动触发压缩：

- **CJK 感知的 token 估算**：拉丁字符约 4 字符/token，中文等 CJK 约 1.5 字符/token。
- **保留最近消息**：压缩时保留最近的 `_MIN_PRESERVE`（12）条消息。
- **结构化摘要**：压缩结果为结构化摘要模板 + 明确的结束标记，保证模型可解析。

手动触发（CLI 中即 `/compact [force]`）：

```python
from agentsx.context.compaction import compact_messages, should_compact

if should_compact(messages):
    messages = compact_messages(messages)
```

### 8.2 压缩审计轨迹

每次压缩都会记录 `compaction_entries`（JSONL 后端的 `compaction.jsonl`，SQLite 后端的同名表），保存被替换消息 ID、摘要与 token 估算，可审计并可重放：

```python
from agentsx.session import create_session_store

store = create_session_store("jsonl")
store.append_compaction_entry(
    session_id,
    replaces_ids=["msg_1", "msg_2"],
    summary="...",
    token_estimate=1200,
)
```

### 8.3 摘要、修剪与轨迹

- `ContextSummarizer`：对上下文做语义摘要（保留最近 10 条，摘要上限 500 token）。
- `tool_pruner`：为每个工具生成单行摘要（`[terminal]` / `[read]` / `[write]`），压缩前修剪。
- `Trajectory`：记录 think / tool_call / tool_result / error 轨迹，便于调试与回放。

### 8.4 快照回滚

压缩前可对关键文件做快照，压缩结果不佳时回滚：

```python
from pathlib import Path
from agentsx.session import SessionSnapshot

snap = SessionSnapshot("session-123", base_dir=Path("."))
snap.capture([Path("src/main.py"), Path("config.yaml")])
# ... 若结果不佳：
snap.rollback()
```

---

## 9. 会话管理

### 9.1 JSONL 后端（默认）

`SessionStore` 将会话保存为 `~/.agentsx/sessions/<session_id>/` 下的文件树（`meta.json` + `messages.jsonl`）。追加写 O(1)，零外部依赖。每条消息结构兼容 JSONL 的追加式写入。

```python
from agentsx.session import SessionStore

store = SessionStore()
sess = store.create(model_name="gpt-4o", title="My Chat")
store.append(sess.id, AgentMessage(role=MessageRole.USER, content="Hi"))
msgs = store.get_messages(sess.id)
```

### 9.2 SQLite + FTS5 后端

需要跨会话全文检索时切换 SQLite 后端（WAL 模式、父-子分支链、FTS5 索引）：

```python
from agentsx.session import create_session_store, create_sqlite_store

store = create_session_store("sqlite")          # 默认 ~/.agentsx/sessions.db
store = create_sqlite_store(db_path="custom.db")  # 显式指定路径

results = store.search("function that reads files")   # (session_id, snippet, rank)
```

`SessionBackend` 协议统一两种后端接口：`create`、`get`、`get_messages`、`append`、`list_sessions`、`delete`、`branch`、`update_title`、`append_compaction_entry`。

### 9.3 分支（Branch）

```python
branch = store.branch(source_id, title="experiment", reason="user")
```

分支继承父会话历史（可指定只复制到某条消息之前），记录 `parent_session_id` 与 `branch_reason`（`user` / `compression` / `delegate`）。

---

## 10. 扩展系统

扩展遵循**观察者 + 拦截器**模式：观察者只记录、不干预；拦截器可以抑制或修改执行流。异常在处理器内被捕获并记录，绝不会导致循环崩溃。

### 10.1 事件类型

观察者事件：

| 常量 | 触发时机 |
|------|----------|
| `EVENT_ON_LOOP_START` | Agent 循环开始 |
| `EVENT_ON_LOOP_END` | Agent 循环结束（正常或出错） |
| `EVENT_ON_MODEL_REQUEST` | 即将调用 LLM |
| `EVENT_ON_MODEL_RESPONSE` | 收到 LLM 响应（delta 或最终） |
| `EVENT_ON_TOOL_CALL` | 模型请求调用工具（执行前） |
| `EVENT_ON_TOOL_RESULT` | 工具执行完成（成功或失败） |
| `EVENT_ON_ERROR` | 循环内发生非致命错误 |

拦截器事件：`EVENT_PRE_TOOL_CALL`、`EVENT_POST_TOOL_CALL`、`EVENT_PRE_COMPACT`、`EVENT_SESSION_START`、`EVENT_SESSION_END`。

### 10.2 注册与使用

```python
import asyncio
from agentsx.extensions import (
    EVENT_ON_TOOL_RESULT,
    ExtensionAPI,
    ExtensionEvent,
)

async def log_tool(event: ExtensionEvent) -> None:
    print("tool finished:", event.data)

api = ExtensionAPI()
api.on(EVENT_ON_TOOL_RESULT, log_tool)

# 在 agent loop 中启用
from agentsx.agent.loop import run_agent_loop
async for event in run_agent_loop(provider, messages, extensions=api):
    ...
```

处理器签名：`Handler = Callable[[ExtensionEvent], Awaitable[None]]`。

### 10.3 拦截器

```python
from agentsx.extensions import EVENT_PRE_TOOL_CALL, InterceptorEvent

async def block_bash(event: InterceptorEvent) -> None:
    if event.data.get("name") == "tool_bash":
        event.suppress()          # 阻止执行
    elif event.data.get("name") == "tool_file_write":
        event.modify({"args": {...}})  # 修改参数

api.on(EVENT_PRE_TOOL_CALL, block_bash)
```

调用方通过 `emit_interceptor()` 返回事件检查 `is_suppressed()` / `is_modified()`。

### 10.4 自动发现

扩展按优先级从四个来源加载（后加载可覆盖先加载）：

1. Python entry points（`group="agentsx.extensions"`，pip 包）
2. 用户目录 `~/.agentsx/extensions/`
3. 项目目录 `.agentsx/extensions/`
4. 内置插件 `agentsx/extensions/builtin/`

每个来源提供一个 `setup(api: ExtensionAPI)` 可调用对象：

```python
# my_extension.py
from agentsx.extensions import ExtensionAPI

def setup(api: ExtensionAPI) -> None:
    api.on(EVENT_ON_LOOP_END, ...)
```

---

## 11. 子代理与编排

### 11.1 派生子代理

通过内置工具 `spawn_agent`，让主代理委派任务给隔离的子代理。子代理拥有独立的 Provider、消息历史与工具注册表：

```python
await registry.call(
    "spawn_agent",
    prompt="List all TODO items in src/",
    role="leaf",          # leaf | orchestrator
    model_name="",        # 空 = 沿用父代理默认模型
    max_steps=10,
    timeout=120,
    max_spawn_depth=2,
)
```

### 11.2 角色隔离

- `leaf`（默认）：聚焦工作单元，**不能**再调用 `spawn_agent`（工具被排除）。
- `orchestrator`：可以派生子代理，深度受 `max_spawn_depth`（默认 2）限制。

子代理默认工具集为只读子集（file_read / glob / grep 等），写、编辑、shell 等变更工具被排除，从机制上防止子代理破坏环境。

### 11.3 编排器

`agentsx.orchestrator.Orchestrator` 管理子代理生命周期，默认限制：同时活跃子代理 `max_active=5`，最大递归深度 `max_spawn_depth=2`。

---

## 12. 工作区与技能发现

### 12.1 工作区感知

- `WorkspaceManager`：识别工作区根目录、Git 状态、文件/目录数量。
- `FileTreeIndex`：构建文件树索引，默认忽略 `.git`、`.venv`、`__pycache__`、`node_modules`、缓存目录等，默认深度 3。
- `GitWatcher`：跟踪分支、修改文件、未跟踪数量与脏状态。
- `ContextProfile`：运行时探测环境姿态（`coding` / `general`），并据此调整上下文与工具集。

```python
from agentsx.workspace import WorkspaceManager

wm = WorkspaceManager(root="/path/to/project")
info = wm.get_info()      # WorkspaceInfo
print(info.has_git, info.file_count)
```

### 12.2 命令与技能发现

`agentsx.discovery` 从目录扫描带 YAML frontmatter 的 `.md` 文件，约定式发现命令与技能：

```python
from agentsx.discovery import discover_commands, discover_skills

commands = discover_commands()   # DiscoveredCommand
skills = discover_skills()       # DiscoveredSkill
```

每个命令/技能由 `name`、`description`、`instructions`、`arguments`、`allowed_tools`、`model` 等元数据描述，可由 Agent 按需加载。

---

## 13. 事件与错误处理

### 13.1 事件流

`run_agent_loop` 产出 `AgentEvent`，常用事件：

| 事件 | 说明 |
|------|------|
| `AgentStartEvent` / `AgentEndEvent` | 循环起止 |
| `ModelRequestEvent` | 即将请求模型 |
| `ModelResponseEvent` | 模型响应；`delta=True` 为流式增量，`delta=False` 为最终完整内容 |
| `ToolCallStreamEvent` | 模型流式产出工具调用 |
| `ToolExecutionEvent` | 工具执行完成，含 `tool_call` 与 `result` |
| `CompactionEvent` | 触发上下文压缩 |
| `RetryEvent` | 进行重试 |
| `ErrorEvent` | 非致命错误 |
| `PromptEvent` | 策略提示（PROMPT 决策） |
| `TextDeltaEvent` / `TextStreamEvent` / `StreamEvent` | 文本流式增量 |

### 13.2 错误层级与分类

- 根异常：`AgentsXError`。
- `ProviderError`：Provider 调用失败，携带 `status_code` 与 `is_retryable`（429 与 5xx 可重试）。
- `RetryExhaustedError`：重试耗尽。
- `ToolError` / `SessionError` / `PolicyError`：工具、会话、策略相关错误。
- `classify_api_error()`：将 API 错误分类为 `ClassifiedError`（含 `FailoverReason` 与 `RecoveryAction`），供故障转移决策。

### 13.3 自动重试

Provider 调用使用 `retry_async` 装饰器实现指数退避 + 抖动（jitter），重试次数与基础延迟由 `AGENTSX_PROVIDER_RETRY_COUNT` / `AGENTSX_PROVIDER_RETRY_BASE_DELAY` 控制。

---

## 14. 配置参考

完整的 `AGENTSX_*` 环境变量清单（对应 `agentsx/config.py` 的 `AgentsXSettings`）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AGENTSX_MODEL_NAME` | `gpt-4o` | 默认模型 |
| `AGENTSX_API_KEY` | 空 | 默认 API Key |
| `AGENTSX_API_BASE` | 空 | 默认 API Base |
| `AGENTSX_MAX_STEPS` | `25` | 工具迭代上限（1–200） |
| `AGENTSX_SYSTEM_PROMPT` | `You are a helpful AI assistant.` | 默认系统提示词 |
| `AGENTSX_SESSION_DIR` | 空 | 会话目录（空 → `~/.agentsx/sessions/`） |
| `AGENTSX_DISCOVERY_DIR` | 空 | 命令/技能发现目录（空 → `~/.agentsx/`） |
| `AGENTSX_POLICY_DEFAULT` | `prompt` | 默认策略 `allow` / `prompt` / `forbidden` |
| `AGENTSX_OPENAI_API_KEY` / `AGENTSX_OPENAI_API_BASE` | 空 | OpenAI |
| `AGENTSX_ANTHROPIC_API_KEY` / `AGENTSX_ANTHROPIC_API_BASE` | 空 | Anthropic |
| `AGENTSX_GEMINI_API_KEY` | 空 | Gemini |
| `AGENTSX_DEEPSEEK_API_KEY` | 空 | DeepSeek |
| `AGENTSX_GROQ_API_KEY` | 空 | Groq |
| `AGENTSX_OPENROUTER_API_KEY` | 空 | OpenRouter |
| `AGENTSX_VLLM_API_KEY` / `AGENTSX_VLLM_API_BASE` | 空 | vLLM |
| `AGENTSX_SGLANG_API_KEY` / `AGENTSX_SGLANG_API_BASE` | 空 | SGLang |
| `AGENTSX_QWEN_API_KEY` / `AGENTSX_QWEN_API_BASE` | 空 | 阿里云 Qwen |
| `AGENTSX_TOOL_TIMEOUT` | `30` | 工具执行超时（秒，1–600） |
| `AGENTSX_PROVIDER_RETRY_COUNT` | `3` | Provider 重试次数（0–10） |
| `AGENTSX_PROVIDER_RETRY_BASE_DELAY` | `1.0` | 重试基础延迟（秒） |
| `AGENTSX_LOOP_TIMEOUT` | `0` | 循环墙钟超时（秒，0 = 禁用） |
| `AGENTSX_MAX_TOOL_OUTPUT` | `50000` | 单工具最大输出字符（0 = 不限） |
| `AGENTSX_WEB_SEARCH_URL` | DuckDuckGo HTML | Web 搜索端点 |
| `AGENTSX_WEB_USER_AGENT` | AgentsX UA | HTTP User-Agent |

在代码中读取配置：

```python
from agentsx.config import get_settings, settings

settings = get_settings()   # 或直接使用模块单例 settings
settings.model_name
settings.max_steps
```

---

## 15. 开发与验证

```bash
uv sync --extra dev

# Lint
uv run ruff check agentsx/ tests/
uv run ruff format --check agentsx/ tests/

# 类型检查（strict）
uv run mypy agentsx/ tests/ --strict

# 测试
uv run python -m pytest -v
```

### 代码约定要点

- Python 3.10+，禁止 `from __future__` 导入；使用 PEP 604 联合类型（`X | Y`）。
- 禁止 `StrEnum`，用 `(str, Enum)` 混入。
- 禁止通配符导入、裸 `except`、行尾空格与 Tab 缩进；行宽上限 88。
- Google 风格 docstring（禁止 Sphinx `:param:`）。
- 完整类型注解；I/O 函数使用 `async def`。
- 硬编码禁令：URL、端口、路径、密钥一律走配置/环境变量。
- 顶层 `agentsx/compaction.py`、`agentsx/extensions.py`、`agentsx/security.py`、`agentsx/session.py` 为**向后兼容别名**（导入即 DeprecationWarning），新代码请从 `agentsx.context`、`agentsx.extensions`、`agentsx.security.policy`、`agentsx.session` 导入。
