# AgentsX

功能性强、简洁、高效、可拓展、高可用的 Agent Harness。

AgentsX 是一个轻量级 AI Agent 运行时框架，提供 ReAct 循环、多 LLM Provider 抽象、内置工具系统、安全策略引擎、会话管理、扩展 API 以及交互式 CLI。

## 特性

- **ReAct Agent 循环** — 纯异步生成器驱动的 think → act → observe → repeat 循环，最大步数可控
- **多 Provider 支持** — OpenAI（含 tool call delta streaming）与 Anthropic（含 tool use streaming），统一 `Provider` 抽象，可通过 `register_provider()` 扩展
- **内置工具系统** — `@tool()` 装饰器 + `ToolRegistry` 自动注册、JSON Schema 生成；8 个内置工具（文件读写、glob、grep、shell、web 抓取与搜索）
- **安全策略引擎** — `Rule` + `ExecutionPolicy`，`fnmatch` 模式匹配，三档决策（ALLOW / PROMPT / FORBIDDEN）；默认策略自动允许只读操作、提示可变操作
- **会话管理** — JSONL 文件树存储（`~/.agentsx/sessions/`），零外部依赖，O(1) 追加写入，支持分支（branch）
- **扩展 API** — `ExtensionAPI` 观察者模式，7 个预定义生命周期事件，异常隔离，支持通过 Python entry points 发现并加载扩展
- **交互式 CLI** — `agentsx chat` 命令，prompt_toolkit 多轮对话、rich 流式输出、工具执行面板、斜杠命令

## 快速开始

### 安装

```bash
# 从源码安装
git clone <repo-url>
cd agentsx
uv sync

# 安装 Provider 可选依赖（按需）
uv sync --extra openai      # OpenAI
uv sync --extra anthropic   # Anthropic
```

### CLI 使用

```bash
# 启动交互式对话（默认模型：gpt-4o）
agentsx chat

# 指定模型
agentsx chat --model claude-sonnet-4-20250514

# 禁用工具
agentsx chat --no-tools

# 跳过安全确认（ALLOW 所有工具）
agentsx chat --allow-all

# 自定义系统提示
agentsx chat --system "You are a coding assistant."
```

环境变量配置（详见下方配置章节）：

```bash
export AGENTSX_MODEL_NAME="gpt-4o"
export AGENTSX_OPENAI_API_KEY="sk-..."
export AGENTSX_ANTHROPIC_API_KEY="sk-ant-..."
```

### Python API

```python
import asyncio
from agentsx.agent.loop import run_agent_loop
from agentsx.core.types import AgentMessage, MessageRole
from agentsx.provider import create_provider
from agentsx.tools import ToolRegistry
from agentsx.tools.builtin import ALL_TOOLS
from agentsx.security import ExecutionPolicy

async def main():
    provider = create_provider(model_name="gpt-4o")
    tools = ToolRegistry()
    tools.register_all(*ALL_TOOLS)

    messages = [
        AgentMessage(role=MessageRole.SYSTEM, content="You are a helpful assistant."),
        AgentMessage(role=MessageRole.USER, content="Read the file README.md and summarize it"),
    ]

    async for event in run_agent_loop(
        provider, messages, tools=tools,
        policy=ExecutionPolicy.default(),
    ):
        print(event)

asyncio.run(main())
```

## 架构

```
agentsx/
├── __init__.py           # 包入口，版本声明
├── config.py             # AgentsXSettings（AGENTSX_* 环境变量）
│
├── core/
│   ├── types.py          # MessageRole, AgentMessage, StreamEvent, Decision, 等
│   └── errors.py         # 类型化异常层级
│
├── provider/
│   ├── __init__.py       # Provider ABC, Model, register_provider(), create_provider()
│   ├── openai.py         # OpenAI 实现（httpx streaming + SSE 解析）
│   └── anthropic.py      # Anthropic 实现（httpx streaming + SSE 解析）
│
├── agent/
│   ├── loop.py           # run_agent_loop() — 纯函数 ReAct 循环
│   └── agent.py          # Agent 类 — 便捷封装
│
├── tools/
│   ├── __init__.py       # ToolSpec, ToolRegistry, @tool()
│   └── builtin/
│       ├── filesystem.py # read, write, edit, glob, grep
│       ├── shell.py      # bash
│       └── web.py        # web_fetch, web_search
│
├── security.py           # Rule, ExecutionPolicy（fnmatch 策略引擎）
├── session.py            # Session, SessionStore（JSONL 文件树）
├── extensions.py         # ExtensionAPI, 7 个事件, entry_points 加载
│
└── cli/
    └── main.py           # typer chat 命令
```

### Agent 循环数据流

```
用户输入 → Provider.stream() → TextStreamEvent → yield ModelResponseEvent(delta)
                                     │
                            ToolCallStreamEvent
                                     │
                          ┌──────────┴──────────┐
                          │  ExecutionPolicy     │
                          │  (ALLOW/PROMPT/FORBIDDEN)
                          └──────────┬──────────┘
                                     │
                          ToolRegistry.call()
                                     │
                          yield ToolExecutionEvent
                                     │
                          追加 ToolResult → 进入下一轮循环
```

## 配置

所有配置通过 `AGENTSX_*` 环境变量注入（Pydantic Settings 驱动）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AGENTSX_MODEL_NAME` | `gpt-4o` | 默认 LLM 模型 |
| `AGENTSX_API_KEY` | `""` | 默认 Provider API 密钥 |
| `AGENTSX_API_BASE` | `""` | 自定义 API 基础 URL |
| `AGENTSX_MAX_STEPS` | `25` | 最大工具调用迭代次数 |
| `AGENTSX_SYSTEM_PROMPT` | `"You are a helpful AI assistant."` | 默认系统提示 |
| `AGENTSX_SESSION_DIR` | `~/.agentsx/sessions/` | 会话存储目录 |
| `AGENTSX_POLICY_DEFAULT` | `"prompt"` | 默认安全策略 |
| `AGENTSX_OPENAI_API_KEY` | `""` | OpenAI API 密钥 |
| `AGENTSX_OPENAI_API_BASE` | `""` | OpenAI API 基础 URL |
| `AGENTSX_ANTHROPIC_API_KEY` | `""` | Anthropic API 密钥 |
| `AGENTSX_ANTHROPIC_API_BASE` | `""` | Anthropic API 基础 URL |
| `AGENTSX_TOOL_TIMEOUT` | `30` | 工具执行超时（秒） |

## 开发

### 环境准备

```bash
uv sync --extra dev
```

### 验证命令

```bash
# 代码检查
uv run ruff check agentsx/ tests/

# 类型检查
uv run mypy agentsx/ tests/ --strict

# 测试
uv run python -m pytest -v
```

## 许可证

Apache 2.0
