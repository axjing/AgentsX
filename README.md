# AgentsX

Feature-rich, clean, efficient, extensible, highly available Agent Harness.

A lightweight AI Agent runtime framework with ReAct loop, multi-Provider abstraction, risk-tiered tool system, multi-layer security, session management, extension API, and interactive CLI.

## Features

- **ReAct Agent Loop** -- async generator-driven think -> act -> observe -> repeat, max steps configurable
- **Multi-Provider** -- OpenAI (with tool call delta streaming) and Anthropic (with tool use streaming), unified Provider ABC, extendable via register_provider()
- **Built-in Tools** -- @tool() decorator + ToolRegistry auto-registration + JSON Schema generation; organized by risk level (read/write/exec/web/orchestration)
- **Multi-Layer Security** -- ExecutionPolicy (ALLOW/PROMPT/FORBIDDEN) + PathGuard (path traversal detection) + CommandGuard (command injection prevention) + ResourceLimits (output truncation)
- **Context Management** -- auto context compaction (token-count + optional LLM summarization)
- **Session Management** -- JSONL file-tree storage (~/.agentsx/sessions/), zero deps, O(1) append writes, branch support
- **Extension API** -- ExtensionAPI observer pattern, 7 lifecycle events, exception isolation, entry_points discovery
- **Interactive CLI** -- agentsx chat, prompt_toolkit, rich streaming, tool panels, slash commands, --workspace flag

## Quick Start

### Installation

```bash
# From source
git clone <repo-url>
cd agentsx
uv sync

# Copy config template
cp .env.example .env
# Edit .env to add your API key

# Install provider optional deps (as needed)
uv sync --extra openai      # OpenAI
uv sync --extra anthropic   # Anthropic
```

### CLI Usage

```bash
# Start interactive chat (default: gpt-4o)
agentsx chat

# Specify model
agentsx chat --model claude-sonnet-4-20250514

# Disable tools
agentsx chat --no-tools

# Skip safety confirmation (ALLOW all tools)
agentsx chat --allow-all

# Restrict file tools to a directory
agentsx chat --workspace /path/to/project

# Custom system prompt
agentsx chat --system "You are a coding assistant."
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
        AgentMessage(role=MessageRole.USER, content="Read README.md and summarize"),
    ]
    async for event in run_agent_loop(provider, messages, tools=tools, policy=ExecutionPolicy.default()):
        print(event)

asyncio.run(main())
```

### Agent Class (Multi-Turn)

```python
from agentsx.agent import Agent

async def main():
    agent = Agent(model_name="gpt-4o")
    async for event in agent.run("What is Python?"):
        pass
    async for event in agent.run("And Rust?"):
        pass  # Remembers first turn
    agent.clear_history()  # Keep system prompt
```

## Architecture

```
agentsx/
├── __init__.py           # Package entry
├── config.py             # Settings (AGENTSX_* env vars)
├── core/                 # Core types & errors
│   ├── types.py
│   └── errors.py
├── context/              # Context management
│   └── compaction.py
├── provider/             # LLM providers
│   ├── __init__.py       # Provider ABC, registry
│   ├── openai.py
│   └── anthropic.py
├── agent/                # Agent logic
│   ├── loop.py           # run_agent_loop()
│   ├── agent.py          # Agent class (multi-turn)
│   └── subagent.py       # SubAgentRuntime
├── tools/                # Tool system
│   ├── __init__.py       # ToolSpec, ToolRegistry, @tool()
│   └── builtin/          # Risk-tiered tools
│       ├── read/           # file_read, file_glob, file_grep
│       ├── write/          # file_write, file_edit
│       ├── exec/           # shell (async, non-blocking)
│       ├── web/            # web_fetch, web_search
│       └── orchestration/  # subagent
├── security/             # Security engine
│   ├── policy.py         # ExecutionPolicy, Rule
│   ├── path_guard.py     # PathGuard
│   ├── command_guard.py  # CommandGuard
│   └── resource_limits.py # ResourceLimits
├── extensions/           # Extension system
│   └── api.py
├── session/              # Session storage
│   └── store.py
├── orchestrator.py       # Sub-agent lifecycle
└── cli/
    ├── main.py           # typer entry
    └── commands.py       # slash commands
```

## Security

AgentsX implements multi-layer security:

1. **ExecutionPolicy** -- fnmatch pattern matching, three-tier decision (ALLOW/PROMPT/FORBIDDEN)
2. **PathGuard** -- path traversal detection (../), symlink attack prevention, workspace boundary enforcement
3. **CommandGuard** -- dangerous command detection (rm -rf /, fork bombs, mkfs) + shell injection pattern detection
4. **ResourceLimits** -- automatic tool output truncation, per-tool-type limits

## Configuration

All config via `AGENTSX_*` environment variables (Pydantic Settings):

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTSX_MODEL_NAME` | `gpt-4o` | Default LLM model |
| `AGENTSX_API_KEY` | `""` | Default Provider API key |
| `AGENTSX_API_BASE` | `""` | Custom API base URL |
| `AGENTSX_MAX_STEPS` | `25` | Max tool-call iterations |
| `AGENTSX_SYSTEM_PROMPT` | `"You are a helpful AI assistant."` | Default system prompt |
| `AGENTSX_SESSION_DIR` | `~/.agentsx/sessions/` | Session storage directory |
| `AGENTSX_POLICY_DEFAULT` | `"prompt"` | Default security policy |
| `AGENTSX_OPENAI_API_KEY` | `""` | OpenAI API key |
| `AGENTSX_ANTHROPIC_API_KEY` | `""` | Anthropic API key |
| `AGENTSX_TOOL_TIMEOUT` | `30` | Tool execution timeout (seconds) |
| `AGENTSX_MAX_TOOL_OUTPUT` | `50000` | Max tool output chars (0 = unlimited) |

## Development

```bash
uv sync --extra dev

# Lint
uv run ruff check agentsx/ tests/

# Type check
uv run mypy agentsx/ tests/ --strict

# Test
uv run python -m pytest -v
```

## License

Apache 2.0
