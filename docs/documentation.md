# AgentsX Documentation

> **Version**: 0.1.0 | **Python**: >=3.10 | **License**: MIT

AgentsX is a lightweight, extensible AI Agent runtime framework. It provides a
ReAct (Think → Act → Observe → Repeat) agent loop, multi-LLM provider
abstraction, a built-in tool system, a three-tier security policy engine,
JSONL-based session persistence, an observer-only extension API, sub-agent
orchestration, and a full-featured interactive CLI.

---

## Table of Contents

1. [Philosophy](#1-philosophy)
2. [Architecture Overview](#2-architecture-overview)
3. [Quick Start](#3-quick-start)
4. [Core Modules](#4-core-modules)
   - 4.1 [Core Types (`core/types.py`)](#41-core-types-coretypespy)
   - 4.2 [Errors (`core/errors.py`)](#42-errors-coreerrorspy)
   - 4.3 [Configuration (`config.py`)](#43-configuration-configpy)
   - 4.4 [Provider Layer (`provider/`)](#44-provider-layer-provider)
   - 4.5 [Agent Loop (`agent/loop.py`)](#45-agent-loop-agentlooppy)
   - 4.6 [Agent Class (`agent/agent.py`)](#46-agent-class-agentagentpy)
   - 4.7 [Tool System (`tools/`)](#47-tool-system-tools)
   - 4.8 [Security Policy (`security.py`)](#48-security-policy-securitypy)
   - 4.9 [Session Store (`session.py`)](#49-session-store-sessionpy)
   - 4.10 [Extension API (`extensions.py`)](#410-extension-api-extensionspy)
   - 4.11 [Sub-Agent Runtime (`agent/subagent.py`)](#411-sub-agent-runtime-agentsubagentpy)
   - 4.12 [Orchestrator (`orchestrator.py`)](#412-orchestrator-orchestratorpy)
   - 4.13 [CLI (`cli/`)](#413-cli-cli)
5. [Slash Commands](#5-slash-commands)
6. [Configuration Reference](#6-configuration-reference)
7. [Extending AgentsX](#7-extending-agentsx)
   - 7.1 [Adding a Provider](#71-adding-a-provider)
   - 7.2 [Adding a Tool](#72-adding-a-tool)
   - 7.3 [Writing an Extension](#73-writing-an-extension)
8. [Development](#8-development)
9. [Design Decisions](#9-design-decisions)

---

## 1. Philosophy

AgentsX was designed by studying four reference projects — Pi, Hermes, Codex
CLI, and Claw Code — and distilling their strengths into a single coherent
codebase while avoiding their weaknesses.

**Core principles:**

- **Simple is effective.** Every abstraction must justify its existence. No
  speculative generality. No over-engineering for scenarios that don't exist.
- **Pure functions where possible.** The agent loop is a stateless async
  generator. Mutable state lives in thin wrappers (`Agent`, `SubAgentRuntime`).
- **Boundaries over coupling.** Provider formats are bridged at I/O boundaries
  via `convert_to_provider()`. Tools don't know about security policy. The agent
  loop doesn't know about sessions.
- **Observability without modification.** Extensions observe events and record
  data; they never alter behaviour. If you need to modify behaviour, write a
  tool instead.
- **Security in the loop.** The three-tier (Allow / Prompt / Forbidden) policy
  engine evaluates every tool call centrally — not scattered across tool
  implementations.

---

## 2. Architecture Overview

```
┌──────────────────────────────────────────────────┐
│                     CLI / API                      │
│    Typer commands  +  prompt_toolkit REPL         │
│    (agentsx/cli/)                                 │
├──────────────────────────────────────────────────┤
│                  Agent Runtime                     │
│    Agent Loop  │  Provider  │  Tools  │  Sessions │
│    (agent/)      (provider/)  (tools/)  (session) │
├──────────────────────────────────────────────────┤
│                  Support Layer                     │
│    Security  │  Extensions  │  Core Types  │  Config│
│    (security)  (extensions)  (core/)       (config)│
└──────────────────────────────────────────────────┘
```

**Dependency direction:** CLI → Agent Runtime → Support Layer. No reverse
dependencies.

### Package Structure

```
agentsx/                          # Python package root
├── __init__.py                   # Package entry, version
├── config.py                     # Pydantic Settings (AGENTSX_* env vars)
├── security.py                   # ExecutionPolicy + Rule
├── session.py                    # SessionStore (JSONL file tree)
├── extensions.py                 # ExtensionAPI + 7 events + entry_points
├── orchestrator.py               # Sub-agent lifecycle management
│
├── core/
│   ├── types.py                  # MessageRole, AgentMessage, ToolCall,
│   │                               ToolResult, AgentEvent, Decision, etc.
│   └── errors.py                 # AgentsXError hierarchy
│
├── provider/
│   ├── __init__.py               # Provider ABC, Model, create_provider(),
│   │                               register_provider()
│   ├── openai.py                 # OpenAI / Azure OpenAI provider
│   └── anthropic.py              # Anthropic Claude provider
│
├── agent/
│   ├── loop.py                   # run_agent_loop() — pure-function ReAct loop
│   ├── agent.py                  # Agent class — convenience wrapper
│   └── subagent.py               # SubAgentRuntime — isolated child agent
│
├── tools/
│   ├── __init__.py               # ToolSpec, ToolRegistry, @tool() decorator
│   └── builtin/
│       ├── __init__.py           # ALL_TOOLS constant
│       ├── filesystem.py         # read, write, edit, glob, grep
│       ├── shell.py              # bash
│       ├── web.py                # web_fetch, web_search
│       └── subagent.py           # spawn_agent tool
│
└── cli/
    ├── main.py                   # Typer app, chat command, _async_chat()
    └── commands.py               # Session slash commands
```

---

## 3. Quick Start

### Installation

```bash
# From source
git clone <repo-url>
cd agentsx
uv sync

# Optional: install provider dependencies
uv sync --extra openai      # OpenAI support
uv sync --extra anthropic   # Anthropic support
```

### CLI Usage

```bash
# Set your API keys
export AGENTSX_OPENAI_API_KEY="sk-..."
export AGENTSX_ANTHROPIC_API_KEY="sk-ant-..."

# Interactive chat
agentsx chat

# With specific model
agentsx chat --model claude-sonnet-4-20250514

# Skip confirmation prompts
agentsx chat --allow-all

# Without built-in tools
agentsx chat --no-tools

# Resume a specific session
agentsx chat --session <session-id>
```

### Python API (Minimal)

```python
import asyncio
from agentsx.agent.loop import run_agent_loop
from agentsx.core.types import AgentMessage, MessageRole
from agentsx.provider import create_provider
from agentsx.tools import ToolRegistry
from agentsx.tools.builtin import ALL_TOOLS

async def main():
    provider = create_provider(model_name="gpt-4o")
    tools = ToolRegistry()
    tools.register_all(*ALL_TOOLS)

    messages = [
        AgentMessage(role=MessageRole.USER, content="Hello!"),
    ]

    async for event in run_agent_loop(provider, messages, tools=tools):
        print(event)

asyncio.run(main())
```

---

## 4. Core Modules

### 4.1 Core Types (`core/types.py`)

All data types shared across the codebase. Provider-agnostic — no module
imports provider-specific types here.

| Type | Description |
|------|-------------|
| `MessageRole` | Enum: `SYSTEM`, `USER`, `ASSISTANT`, `TOOL` |
| `ToolCall` | A tool invocation requested by the LLM (`id`, `name`, `arguments`) |
| `ToolResult` | The result of executing a tool call (`content`, `is_error`) |
| `AgentMessage` | Internal message representation with `convert_to_provider()` bridge |
| `ModelRequestEvent` | Emitted before each LLM call |
| `ModelResponseEvent` | Emitted for each token (delta) and once for the final response |
| `ToolExecutionEvent` | Emitted after each tool call completes |
| `ErrorEvent` | Emitted on non-fatal errors during the loop |
| `AgentEvent` | Union of the four event types above |
| `TextStreamEvent` | Text token yielded by `Provider.stream()` |
| `ToolCallStreamEvent` | Complete tool call yielded by `Provider.stream()` |
| `StreamEvent` | Union of text and tool-call stream events |
| `Decision` | Security decision: `ALLOW`, `PROMPT`, `FORBIDDEN` |

**Key design — `AgentMessage.convert_to_provider()`:**

```python
message = AgentMessage(role=MessageRole.USER, content="Hello")
openai_msg = message.convert_to_provider("openai")
anthropic_msg = message.convert_to_provider("anthropic")
```

This bridges internal types to provider-native formats at the I/O boundary.
The agent loop never sees provider-specific dicts.

### 4.2 Errors (`core/errors.py`)

Single-inheritance exception hierarchy:

```
AgentsXError
├── ProviderError     # LLM API errors (auth, rate-limit, network)
├── ToolError         # Tool execution failures
├── PolicyError       # Security policy violations
└── SessionError      # Session storage errors
```

### 4.3 Configuration (`config.py`)

All configuration uses Pydantic Settings with the `AGENTSX_` prefix:

```python
from agentsx.config import settings

settings.model_name        # "gpt-4o"
settings.max_steps         # 25
settings.openai_api_key    # from AGENTSX_OPENAI_API_KEY
```

A `get_settings()` function is available for call-time access (preferred in
provider modules to allow reconfiguration after import).

### 4.4 Provider Layer (`provider/`)

The `Provider` ABC defines a single abstract method:

```python
class Provider(ABC):
    model: Model

    @abstractmethod
    async def stream(
        self,
        messages: list[AgentMessage],
    ) -> AsyncIterator[StreamEvent]:
        """Yields TextStreamEvent and ToolCallStreamEvent."""
```

**Registry pattern:**

```python
from agentsx.provider import register_provider, create_provider

register_provider("openai", OpenAIProvider)
provider = create_provider(model_name="gpt-4o")
```

Built-in providers:

| Provider | Model prefix | File |
|----------|-------------|------|
| OpenAI | `gpt-` | `provider/openai.py` |
| Anthropic | `claude-` | `provider/anthropic.py` |

Both use raw `httpx` streaming (no official SDK dependency required at import
time). Tool-call detection is handled by parsing SSE chunks — delta
accumulation for OpenAI, content-block events for Anthropic.

### 4.5 Agent Loop (`agent/loop.py`)

The heart of AgentsX — a pure async generator implementing the ReAct pattern.

```
                        ┌──────────────────┐
                        │  Agent Loop       │
                        │  run_agent_loop() │
                        └────────┬─────────┘
                                 │
                    ┌────────────┴────────────┐
                    │  Step 1: Call LLM        │
                    │  yield ModelRequestEvent │
                    │  yield ModelResponseEvent│
                    │  (token by token)        │
                    └────────────┬────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │  Tool calls requested?   │
                    │  ── No ──▶ break (done)  │
                    │  ── Yes ─▶ evaluate each  │
                    └────────────┬────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │  Policy Gate             │
                    │  Decision.ALLOW    ──▶ execute  │
                    │  Decision.PROMPT   ──▶ return   │
                    │                        error    │
                    │  Decision.FORBIDDEN─▶  return   │
                    │                        error    │
                    └────────────┬────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │  yield ToolExecutionEvt  │
                    │  Append result → messages│
                    │  Loop back to Step 1     │
                    └─────────────────────────┘
```

**Signature:**

```python
async def run_agent_loop(
    provider: Provider,
    messages: list[AgentMessage],
    max_steps: int | None = None,
    tools: ToolRegistry | None = None,
    policy: ExecutionPolicy | None = None,
    extensions: ExtensionAPI | None = None,
) -> AsyncIterator[AgentEvent]:
```

Key characteristics:
- **Pure function.** No mutable state held outside the local scope. The
  `messages` list is modified in-place (appended with assistant responses and
  tool results) — this is the only side effect.
- **Streaming-first.** Text tokens yield `ModelResponseEvent(delta=True)` as
  they arrive, enabling real-time display in the CLI.
- **Tool execution is sequential.** Each tool call in a batch is executed
  one-by-one. Parallel execution is deferred until profiling shows it as a
  bottleneck.
- **Extensions are observer-only.** Handlers receive events, can log or record
  them, but cannot modify behaviour or abort the loop.

### 4.6 Agent Class (`agent/agent.py`)

Thin convenience wrapper around `run_agent_loop()`:

```python
agent = Agent(model_name="gpt-4o")
async for event in agent.run("Read README.md"):
    if isinstance(event, ModelResponseEvent):
        print(event.content, end="")
```

Holds optional `Provider`, `ToolRegistry`, `ExecutionPolicy`, and
`ExtensionAPI` instances. Resolves the provider automatically from
configuration if not provided.

### 4.7 Tool System (`tools/`)

**`ToolSpec`** — tool descriptor with name, description, callable, and JSON
Schema (auto-derived from function signature via `inspect`).

```python
spec = ToolSpec(
    name="read",
    description="Read a file",
    fn=my_read_function,
)
await spec.call(path="/tmp/file.txt")
```

**`ToolRegistry`** — manages a collection of `ToolSpec` instances:

```python
registry = ToolRegistry()
registry.register(tool_file_read)
registry.register_all(*ALL_TOOLS)
await registry.call("read", path="/tmp/file.txt")
```

**`@tool()` decorator** — wraps any function into a `ToolSpec`:

```python
@tool(description="Read a file from the local filesystem.")
def tool_file_read(path: str, offset: int = 0, limit: int = 0) -> str:
    ...
```

JSON Schema is generated automatically from the function signature via
`inspect.signature()`. Async functions are detected and awaited automatically
in `ToolSpec.call()`.

#### Built-in Tools

| Tool | File | Description |
|------|------|-------------|
| `tool_file_read` | `filesystem.py` | Read file contents with offset/limit |
| `tool_file_write` | `filesystem.py` | Write content to a file (overwrite) |
| `tool_file_edit` | `filesystem.py` | Exact-text replacement in a file |
| `tool_file_glob` | `filesystem.py` | Find files by glob pattern |
| `tool_file_grep` | `filesystem.py` | Search file contents by regex |
| `tool_bash` | `shell.py` | Execute a shell command |
| `tool_web_fetch` | `web.py` | Fetch a URL and return as text |
| `tool_web_search` | `web.py` | Web search via DuckDuckGo Lite |
| `spawn_agent` | `subagent.py` | Spawn an isolated sub-agent |

All built-in tools are exported via `ALL_TOOLS`:

```python
from agentsx.tools.builtin import ALL_TOOLS
# ALL_TOOLS is a list of 9 ToolSpec instances
```

### 4.8 Security Policy (`security.py`)

Three-tier decision model inspired by Codex CLI:

| Decision | Meaning |
|----------|---------|
| `ALLOW` | Execute without confirmation |
| `PROMPT` | Ask the user before executing (safe default) |
| `FORBIDDEN` | Block unconditionally |

**Rules** use `fnmatch` pattern matching against a combined string of
`"tool_name:{json_args}"`:

```python
Rule("read:*", Decision.ALLOW)          # all read calls allowed
Rule("bash:rm *", Decision.FORBIDDEN)   # rm forbidden in bash
Rule("*", Decision.PROMPT)              # everything else: prompt
```

**`ExecutionPolicy.default()`** factory — safe defaults:

| Pattern | Decision |
|---------|----------|
| `read:*`, `glob:*`, `grep:*` | ALLOW |
| `web_fetch:*`, `web_search:*` | ALLOW |
| `write:*`, `edit:*`, `bash:*` | PROMPT |
| Everything else | PROMPT |

### 4.9 Session Store (`session.py`)

Zero-dependency JSONL file-tree storage, inspired by Pi's session design.

**Directory structure:**

```
~/.agentsx/sessions/
└── <session_id>/
    ├── meta.json           # Session metadata (JSON)
    └── messages.jsonl      # One JSON message per line, append-only
```

**API:**

| Method | Description |
|--------|-------------|
| `create(model_name, title)` | Create a new session |
| `get(session_id)` | Load session metadata |
| `get_messages(session_id)` | Load all messages |
| `append(session_id, message)` | Append one message (O(1)) |
| `list()` | List all sessions, newest first |
| `delete(session_id)` | Permanently delete a session |
| `branch(session_id, title)` | Fork a session (copy messages to new ID) |

Design properties:
- **Append-only writes.** No locking required. Safe for concurrent appends.
- **Plain text.** Grep-friendly messages for debugging.
- **Branch by copy.** The original session is never modified.
- **No database, no migrations.** A session is just two files on disk.

### 4.10 Extension API (`extensions.py`)

Observer-only pattern — extensions can observe and record but never modify
behaviour. Design avoids the Hermes 8-hook plugin trap:

> *"If you need to modify behaviour, write a tool instead."*

**Predefined events:**

| Constant | Fired when |
|----------|-----------|
| `EVENT_ON_LOOP_START` | Agent loop iteration begins |
| `EVENT_ON_LOOP_END` | Agent loop iteration ends |
| `EVENT_ON_MODEL_REQUEST` | About to call the LLM |
| `EVENT_ON_MODEL_RESPONSE` | Received a token/response from the LLM |
| `EVENT_ON_TOOL_CALL` | Tool call requested by the LLM |
| `EVENT_ON_TOOL_RESULT` | Tool execution completed |
| `EVENT_ON_ERROR` | Non-fatal error occurred |

**Usage:**

```python
from agentsx.extensions import ExtensionAPI, ExtensionEvent

api = ExtensionAPI()

api.on("on_tool_result", lambda e: print(e.data))
await api.emit(ExtensionEvent(
    type="on_tool_result",
    data={"tool": "read", "duration_ms": 42},
))
```

**Auto-discovery** via Python entry points (group: `agentsx.extensions`):

```python
api.load_entry_points()  # discovers and calls setup(api) for each entry point
```

Exception isolation: exceptions in handlers are caught and logged. They never
propagate to the caller.

### 4.11 Sub-Agent Runtime (`agent/subagent.py`)

An isolated ReAct agent runtime that runs independently with its own Provider,
message history, and tool subset.

```python
config = SubAgentConfig(
    model_name="gpt-4o",
    system_prompt="You are a code reviewer.",
    max_steps=10,
)
runtime = SubAgentRuntime(config)
result = await runtime.run("Review the file README.md")
```

**Default tool set (read-only):**

- `tool_file_read`
- `tool_file_glob`
- `tool_file_grep`
- `tool_web_fetch`
- `tool_web_search`

Mutation tools (`write`, `edit`, `bash`) are excluded by default unless
explicitly whitelisted via `allowed_tools`.

### 4.12 Orchestrator (`orchestrator.py`)

Manages sub-agent lifecycles with resource limits.

```python
orchestra = Orchestrator(max_active=5)
result = await orchestra.spawn(config, prompt)
```

- Enforces `max_active` concurrent sub-agents
- Tracks each sub-agent with metadata (id, model, prompt, status)
- Enforces timeout via `asyncio.wait_for`
- Cleans up completed/failed agents from tracking

### 4.13 CLI (`cli/`)

**`cli/main.py`** — Typer application with the `chat` command:

```
agentsx chat [--model] [--system] [--no-tools] [--max-steps]
             [--allow-all] [--session]
```

The chat loop:
1. Resolves provider model and API key
2. Creates or loads a session via `SessionStore`
3. Initialises tool registry (optional) and security policy
4. Displays welcome panel with model, session, and tools info
5. Enters REPL: reads user input, dispatches `/slash` commands, or runs the
   agent loop with rich streaming output and tool execution panels

**`cli/commands.py`** — Session management slash commands (see Section 5).

---

## 5. Slash Commands

Available in the `agentsx chat` REPL:

| Command | Description |
|---------|-------------|
| `/sessions` | List all sessions (active session marked) |
| `/session show <id>` | Show session details and recent messages |
| `/session switch <id>` | Switch to a different session |
| `/new [title]` | Create a new session |
| `/delete <id>` | Delete a session (cannot delete the active one) |
| `/branch <id> [title]` | Fork a session with its message history |
| `/title <name>` | Rename the current session |
| `/clear` | Clear conversation history (in-memory) |
| `/help` | Show this command list |
| `/exit`, `/quit` | Exit the chat |

Session switching reloads the full message history from disk. Session data is
persisted automatically after every turn.

---

## 6. Configuration Reference

All settings via `AGENTSX_*` environment variables (Pydantic Settings):

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTSX_MODEL_NAME` | `gpt-4o` | Default LLM model |
| `AGENTSX_API_KEY` | `""` | Default API key |
| `AGENTSX_API_BASE` | `""` | Custom API base URL |
| `AGENTSX_MAX_STEPS` | `25` | Max tool-calling iterations |
| `AGENTSX_SYSTEM_PROMPT` | `"You are a helpful AI assistant."` | Default system prompt |
| `AGENTSX_SESSION_DIR` | `~/.agentsx/sessions/` | Session storage directory |
| `AGENTSX_POLICY_DEFAULT` | `"prompt"` | Default security policy |
| `AGENTSX_OPENAI_API_KEY` | `""` | OpenAI API key |
| `AGENTSX_OPENAI_API_BASE` | `""` | OpenAI API base URL |
| `AGENTSX_ANTHROPIC_API_KEY` | `""` | Anthropic API key |
| `AGENTSX_ANTHROPIC_API_BASE` | `""` | Anthropic API base URL |
| `AGENTSX_TOOL_TIMEOUT` | `30` | Tool execution timeout (seconds) |

Settings can also be loaded from a `.env` file in the project root.

---

## 7. Extending AgentsX

### 7.1 Adding a Provider

1. Create a new file in `agentsx/provider/` (e.g. `google.py`)
2. Subclass `Provider` and implement `stream()`
3. Call `register_provider()` at module level

```python
from agentsx.provider import Provider, register_provider
from agentsx.core.types import StreamEvent, AgentMessage
from agentsx.core.errors import ProviderError

class GoogleProvider(Provider):
    async def stream(
        self,
        messages: list[AgentMessage],
    ) -> AsyncIterator[StreamEvent]:
        # Convert messages via message.convert_to_provider("google")
        # Yield TextStreamEvent and ToolCallStreamEvent
        ...

register_provider("google", GoogleProvider)
```

The model prefix (`"gemini-"`) must be added to `_provider_prefix()` in
`provider/__init__.py` for `create_provider()` auto-detection.

### 7.2 Adding a Tool

1. Create a new file in `agentsx/tools/builtin/` (or add to an existing one)
2. Define a function with the `@tool()` decorator
3. Export it in `builtin/__init__.py` and add to `ALL_TOOLS`

```python
# agentsx/tools/builtin/mytool.py
from agentsx.tools import tool

@tool(description="Do something useful.")
def tool_my_action(param1: str, param2: int = 42) -> str:
    """Do something useful.

    Args:
        param1: A required string parameter.
        param2: An optional integer parameter (default 42).

    Returns:
        A result string.
    """
    return f"Did it: {param1}, {param2}"
```

Parameters are automatically introspected into a JSON Schema. The function
may be sync or async — `ToolSpec.call()` handles both.

### 7.3 Writing an Extension

1. Create any Python module
2. Define a setup function that accepts `ExtensionAPI`
3. Register via entry points in `pyproject.toml` (under `[project.entry-points."agentsx.extensions"]`)

```python
# my_extension.py
from agentsx.extensions import ExtensionAPI, ExtensionEvent

def setup(api: ExtensionAPI) -> None:
    api.on("on_tool_result", log_tool_result)

async def log_tool_result(event: ExtensionEvent) -> None:
    print(f"Tool: {event.data['name']}, success: {event.data['success']}")
```

`pyproject.toml` registration:

```toml
[project.entry-points."agentsx.extensions"]
my-extension = "my_extension:setup"
```

---

## 8. Development

### Environment Setup

```bash
uv sync --extra dev
```

Activate the virtual environment:

- Windows: `.venv\Scripts\activate`
- Unix: `source .venv/bin/activate`

### Validation Commands

```bash
# Code linting
uv run ruff check agentsx/ tests/

# Format check
uv run ruff format --check agentsx/ tests/

# Type checking (strict mode)
uv run mypy agentsx/ tests/ --strict

# Tests
uv run python -m pytest -v

# Tests with coverage
uv run python -m pytest -v --cov=agentsx
```

### Code Style

- Line length: 88 characters (ruff default)
- Indentation: 4 spaces
- Quotes: double quotes
- Imports: standard library → third-party → project internal → relative
- `from __future__ import annotations` in every file
- Google-style docstrings
- Full type annotations on all functions and variables
- No `as any`, `@ts-ignore`, `@ts-expect-error` (Python equivalents prohibited)

### Project-Specific Conventions

- `Provider` pattern: subclass `Provider` ABC; register via `register_provider()`,
  create via `create_provider()`
- Agent loop: `run_agent_loop()` is a pure async generator
- Tool system: `@tool()` decorator auto-generates JSON Schema; register in
  `ToolRegistry`
- Security: `ExecutionPolicy` evaluates `fnmatch` patterns; default allows
  read-only tools, prompts mutations
- Session: `SessionStore` stores conversations as JSONL files
- Extensions: `ExtensionAPI` observer-only; `on()` registers, `emit()` fires
- Config: all via `AGENTSX_*` environment variables
- Async: all I/O-bound functions use `async def`

---

## 9. Design Decisions

### Why a pure async generator for the agent loop?

Pi's `EventStream<AgentEvent>` pattern proved that a stateless, streaming
interface is more composable than a class with mutable state. The CLI can
consume events for real-time display, tests can collect them for assertions,
and higher-level wrappers (`Agent` class) can add convenience without
sacrificing the simple core.

### Why three-tier security instead of binary allow/deny?

Codex CLI's Allow/Prompt/Forbidden model gives a third option that balances
safety with usability. Read operations (`read`, `glob`, `grep`) are allowed
automatically (no friction). Mutation operations (`bash`, `write`) require
confirmation (safe by default). Users who trust the agent can escalate to
`--allow-all`.

### Why observer-only extensions?

Hermes Agent's 8-hook plugin system adds complexity with unclear benefit.
Most "extensions" just want to observe events (logging, telemetry, analytics).
If an extension needs to modify behaviour, it should be a tool — which is a
simpler, more testable abstraction.

### Why JSONL file tree for sessions?

Pi's approach — one directory per session, `messages.jsonl` for append-only
writes — is zero-dependency, grep-friendly, and fast enough for 10K+ messages.
SQLite would add a build dependency and migration overhead without meaningful
benefit at this scale.

### Why raw httpx instead of official SDKs?

The official OpenAI and Anthropic SDKs are large dependencies with their own
type systems and error handling. Using raw `httpx` streaming keeps the
dependency footprint small and gives full control over the HTTP layer. The
SDK can be added as an optional dependency if advanced features (e.g. streaming
tool call validation) are needed later.

### Why no parallel tool execution?

Sequential execution is simpler, easier to debug, and sufficient for the vast
majority of agent workflows. Parallel execution adds race-condition risks,
output-ordering complexity, and resource contention. It will be added only if
profiling shows it as a bottleneck.

### Circular import avoidance in sub-agent module

The `spawn_agent` tool is registered in `builtin/__init__.py` but needs to
import `SubAgentRuntime` from `agent/subagent.py`, which imports tools from
`builtin/*`. This creates a circular chain. Two strategies break it:

1. **Lazy imports** — imports inside function bodies in `subagent.py` tool
2. **Direct module imports** — importing from individual tool modules (e.g.
   `agentsx.tools.builtin.filesystem`) instead of via `builtin/__init__`

Both are documented with `# noqa: PLC0415` comments.
