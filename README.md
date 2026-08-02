# AgentsX

Feature-rich, clean, efficient, extensible, highly available Agent Harness.

A lightweight AI Agent runtime framework with ReAct loop, multi-Provider abstraction, risk-tiered tool system, multi-layer security, session management, extension API, and interactive CLI.

## Features

- **ReAct Agent Loop** -- async generator-driven think -> act -> observe -> repeat, max steps configurable
- **Multi-Provider** -- 9 providers via profile system (OpenAI, Anthropic, Gemini, DeepSeek, Groq, OpenRouter, Ollama, vLLM, SGLang), Transport/Provider two-layer abstraction, GenericProvider covers any OpenAI-compatible endpoint
- **Built-in Tools** -- @tool() decorator + ToolRegistry auto-registration + JSON Schema generation; organized by risk level (read/write/exec/web/orchestration/mcp)
- **Multi-Layer Security** -- ExecutionPolicy (ALLOW/PROMPT/FORBIDDEN) + PathGuard (path traversal detection) + CommandGuard (command injection prevention) + ResourceLimits (output truncation)
- **Context Management** -- auto context compaction (token-count + optional LLM summarization), CJK-aware token estimation, append-only compaction audit trail
- **Session Management** -- JSONL file-tree (default) + SQLite with FTS5 (optional), SessionBackend Protocol, zero deps, O(1) append writes, branch support
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
from agentsx.protocol.messages import AgentMessage, MessageRole
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

> Detailed technical solution: [docs/architecture.md](docs/architecture.md) · Usage tutorial: [docs/tutorial.md](docs/tutorial.md)

```
agentsx/
├── __init__.py           # Package entry
├── config.py             # Settings (AGENTSX_* env vars)
├── protocol/             # Data contract (messages, events, errors)
│   ├── __init__.py       # Unified re-exports
│   ├── messages.py       # AgentMessage, ToolCall, ContentPart, ToolResult
│   ├── events.py         # All AgentEvent / StreamEvent types
│   └── errors.py         # Exception hierarchy + error classification
├── context/              # Context management
│   ├── compaction.py     # Token-count based compaction (CJK-aware)
│   ├── compaction_entry.py  # Append-only audit trail + replay
│   ├── summarizer.py     # Semantic summaries
│   ├── trajectory.py     # Think/tool_call/result/error tracking
│   └── manager.py        # Unified interface
├── provider/             # LLM provider abstraction
│   ├── __init__.py       # Thin re-export
│   ├── abc.py            # Provider ABC + Model class
│   ├── converters.py     # Provider message format conversion
│   ├── factory.py        # create_provider() factory
│   ├── registry.py       # _PROVIDER_REGISTRY + register_provider()
│   ├── transport.py      # ProviderTransport ABC, OpenAI/Anthropic adapters
│   ├── generic.py        # GenericProvider (OpenAI-compatible endpoints)
│   ├── profile.py        # 9 provider profiles (model aliases, URLs, env vars)
│   └── retry.py          # Retry logic
├── agent/                # Agent execution
│   ├── loop.py           # run_agent_loop() — pure async generator
│   ├── harness.py        # AgentHarness — stateful multi-turn wrapper
│   ├── agent.py          # Agent convenience class
│   └── subagent.py       # SubAgentRuntime
├── tools/                # Tool system
│   ├── __init__.py       # ToolSpec, ToolRegistry, @tool()
│   └── builtin/          # Risk-tiered tools
│       ├── read/           # file_read, file_glob, file_grep
│       ├── write/          # file_write, file_edit
│       ├── exec/           # shell (async, non-blocking)
│       ├── web/            # web_fetch, web_search
│       ├── orchestration/  # subagent
│       └── mcp/            # MCP client (tool_mcp_call)
├── security/             # Security engine
│   ├── __init__.py       # Exports all security classes
│   ├── policy.py         # ExecutionPolicy, Rule
│   ├── path_guard.py     # PathGuard (symlink, junction, traversal)
│   ├── command_guard.py  # CommandGuard (injection detection)
│   └── resource_limits.py # ResourceLimits (output truncation)
├── extensions/           # Extension system
│   └── api.py            # ExtensionAPI (observer-only, 7 events)
├── session/              # Session storage
│   ├── __init__.py       # Session, SessionStore, SQLiteSessionStore
│   ├── store.py          # JSONL file-tree (default)
│   ├── sqlite_store.py   # SQLite with FTS5 (optional)
│   └── protocol.py       # SessionBackend Protocol
├── discovery/            # File-based command/skill discovery
│   ├── loader.py         # Frontmatter parser + directory scanner
│   └── models.py         # DiscoveredCommand, DiscoveredSkill
├── workspace/            # Workspace awareness
│   ├── manager.py        # WorkspaceManager (git detection, file counts)
│   ├── git.py            # Git status watcher
│   └── context_profile.py # Runtime posture detection (coding/general)
├── orchestrator.py       # Sub-agent lifecycle manager
└── cli/
    ├── main.py           # typer entry: chat, run
    ├── commands.py       # slash command implementations
    └── repl.py           # REPL display + command dispatch
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
