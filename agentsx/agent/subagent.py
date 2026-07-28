"""Isolated sub-agent runtime for orchestration.

Each ``SubAgentRuntime`` runs an independent ReAct loop with its own
Provider, message state, and tool subset.  Results are returned as plain
text so the parent agent can consume them via a tool result.

Role isolation (inspired by Hermes-Agent's delegate_tool.py):
    - ``LEAF``: focused worker, cannot delegate further.
    - ``ORCHESTRATOR``: can spawn its own child agents.

Tool blocking prevents dangerous operations in child agents.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4

from agentsx.agent.loop import run_agent_loop
from agentsx.protocol.events import (
    AgentEvent,
    ModelResponseEvent,
)
from agentsx.protocol.messages import (
    AgentMessage,
    MessageRole,
)
from agentsx.provider import Provider, create_provider
from agentsx.security.policy import ExecutionPolicy
from agentsx.tools import ToolRegistry
from agentsx.tools.builtin.exec.shell import tool_bash
from agentsx.tools.builtin.read.filesystem import (
    tool_file_glob,
    tool_file_grep,
    tool_file_read,
)
from agentsx.tools.builtin.web.web import tool_web_fetch, tool_web_search
from agentsx.tools.builtin.write.filesystem import (
    tool_file_edit,
    tool_file_write,
)

# All built-in tools (used to build permissive registries).
_ALL_BUILTIN_TOOLS = [
    tool_file_read,
    tool_file_write,
    tool_file_edit,
    tool_file_glob,
    tool_file_grep,
    tool_bash,
    tool_web_fetch,
    tool_web_search,
]

# Tools allowed for sub-agents by default (read-only subset).
_SUBAGENT_ALLOWED_TOOLS = {
    "tool_file_read",
    "tool_file_glob",
    "tool_file_grep",
    "tool_web_fetch",
    "tool_web_search",
}

# Tools that child agents must never have access to, regardless of role.
# Inspired by Hermes-Agent's DELEGATE_BLOCKED_TOOLS.
DELEGATE_BLOCKED_TOOLS: frozenset[str] = frozenset(
    {
        "spawn_agent",  # prevent recursive delegation from leaf agents
    }
)


class SubAgentRole(str, Enum):
    """Role determining what a sub-agent can do.

    ``LEAF`` is the default: a focused worker that cannot delegate further.
    ``ORCHESTRATOR`` can spawn its own child agents (bounded by
    ``max_spawn_depth``).
    """

    LEAF = "leaf"
    ORCHESTRATOR = "orchestrator"


@dataclass
class SubAgentConfig:
    """Configuration for a sub-agent runtime."""

    model_name: str
    """Model identifier for the sub-agent (e.g. ``"gpt-4o"``)."""

    system_prompt: str = ""
    """Optional system prompt.  Empty = no system message."""

    max_steps: int = 10
    """Maximum tool-calling iterations."""

    allowed_tools: list[str] | None = None
    """Tool names the sub-agent may use.  ``None`` = default read-only set."""

    blocked_tools: frozenset[str] = field(
        default_factory=lambda: DELEGATE_BLOCKED_TOOLS,
    )
    """Tool names to always exclude, on top of role-based restrictions."""

    role: SubAgentRole = SubAgentRole.LEAF
    """Sub-agent role: ``LEAF`` (no delegation) or ``ORCHESTRATOR``."""

    timeout: int = 120
    """Wall-clock timeout in seconds (not yet enforced at runtime)."""

    max_spawn_depth: int = 2
    """Maximum depth for recursive sub-agent spawning."""

    current_depth: int = 0
    """Current recursion depth (used for depth-limit enforcement)."""


class SubAgentRuntime:
    """Isolated ReAct agent runtime.

    Each instance has its own Provider, messages, and ToolRegistry.
    The ``run()`` method executes a full agent loop and returns the
    final response text.

    Role isolation:
        - ``LEAF`` agents cannot call ``spawn_agent`` (tool is excluded).
        - ``ORCHESTRATOR`` agents can spawn children up to ``max_spawn_depth``.

    Usage::

        config = SubAgentConfig(model_name="gpt-4o")
        runtime = SubAgentRuntime(config)
        result = await runtime.run("Read the file README.md")
    """

    def __init__(self, config: SubAgentConfig, spawn_depth: int = 0) -> None:
        self._id: str = uuid4().hex[:12]
        self._config = config
        self._provider: Provider = create_provider(model_name=config.model_name)
        self._tools: ToolRegistry = _build_subagent_tools(
            config.allowed_tools,
            blocked=config.blocked_tools,
            role=config.role,
        )
        self._messages: list[AgentMessage] = []
        self._spawn_depth = spawn_depth

        if config.system_prompt:
            self._messages.append(
                AgentMessage(role=MessageRole.SYSTEM, content=config.system_prompt),
            )

    @property
    def id(self) -> str:
        """Unique identifier for this sub-agent instance."""
        return self._id

    @property
    def messages(self) -> list[AgentMessage]:
        """Read-only access to the sub-agent's message history."""
        return list(self._messages)

    @property
    def model_name(self) -> str:
        """The model identifier for this sub-agent."""
        return self._config.model_name

    @property
    def spawn_depth(self) -> int:
        """Current depth of recursive spawning."""
        return self._spawn_depth

    @property
    def role(self) -> SubAgentRole:
        """The sub-agent's role."""
        return self._config.role

    async def run(self, prompt: str) -> str:
        """Run the sub-agent on *prompt* and return the final response.

        Args:
            prompt: The task description passed as a user message.

        Returns:
            The concatenated assistant response (non-delta content).
        """
        self._messages.append(
            AgentMessage(role=MessageRole.USER, content=prompt),
        )

        result_parts: list[str] = []
        async for event in self._loop():
            if isinstance(event, ModelResponseEvent) and not event.delta:
                result_parts.append(event.content)

        return "\n".join(result_parts)

    async def _loop(self) -> AsyncIterator[AgentEvent]:
        """Run the ReAct loop with this sub-agent's isolated state."""
        async for event in run_agent_loop(
            provider=self._provider,
            messages=self._messages,
            max_steps=self._config.max_steps,
            tools=self._tools,
            policy=ExecutionPolicy.default(),
        ):
            yield event

    def __repr__(self) -> str:
        return (
            f"SubAgentRuntime(id={self._id!r}, "
            f"model={self._config.model_name!r}, "
            f"role={self._config.role.value!r}, "
            f"depth={self._spawn_depth}, "
            f"steps={self._config.max_steps})"
        )


def _build_subagent_tools(
    allowed_tools: list[str] | None,
    blocked: frozenset[str] | None = None,
    role: SubAgentRole = SubAgentRole.LEAF,
) -> ToolRegistry:
    """Build a ToolRegistry restricted to *allowed_tools* minus *blocked*.

    Args:
        allowed_tools: Explicit allow-list.  ``None`` = default read-only set.
        blocked: Tools to always exclude (on top of role restrictions).
        role: Sub-agent role.  ``LEAF`` excludes ``spawn_agent``.

    When *allowed_tools* is ``None``, uses the default read-only subset
    (excluding write, edit, bash, and other mutation tools).
    """
    names = _SUBAGENT_ALLOWED_TOOLS if allowed_tools is None else set(allowed_tools)

    # Role-based restrictions
    if role == SubAgentRole.LEAF:
        names = names - {"spawn_agent"}

    # Explicit block list (always applied)
    if blocked:
        names = names - blocked

    registry = ToolRegistry()
    for tool_spec in _ALL_BUILTIN_TOOLS:
        if tool_spec.name in names:
            registry.register(tool_spec)
    return registry
