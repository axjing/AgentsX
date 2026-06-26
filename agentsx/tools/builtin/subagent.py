"""Sub-agent orchestration tool — ``spawn_agent``.

Allows the parent agent to delegate tasks to an isolated child agent
with its own model, message context, and tool subset.

Note: imports from ``agentsx.agent.subagent`` and ``agentsx.orchestrator``
are lazy (inside the function body) to avoid a circular import chain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentsx.tools import tool

if TYPE_CHECKING:
    from agentsx.orchestrator import Orchestrator

# Module-level orchestrator singleton — shared across tool calls.
_orchestra: Any = None


def _get_orchestra() -> Orchestrator:
    """Get or create the global orchestrator singleton."""
    from agentsx.orchestrator import Orchestrator as _Orc  # noqa: PLC0415

    global _orchestra  # noqa: PLW0603
    if _orchestra is None:
        _orchestra = _Orc(max_active=5)
    return _orchestra  # type: ignore[no-any-return]


@tool(
    description=(
        "Spawn an isolated sub-agent to perform a task, then return its response."
    ),
)
async def spawn_agent(
    model_name: str = "",
    prompt: str = "",
    system_prompt: str = "",
    max_steps: int = 10,
    timeout: int = 120,
    max_spawn_depth: int = 2,
) -> str:
    """Spawn a sub-agent with its own context and tool set.

    The sub-agent runs independently with its own Provider, message
    history, and restricted tool subset (read-only by default).

    Args:
        model_name: Model to use (empty = parent's default model).
        prompt: The detailed task prompt for the sub-agent.
        system_prompt: Optional system prompt for the sub-agent.
        max_steps: Max tool-calling iterations (default 10).
        timeout: Max wall-clock seconds (default 120).
        max_spawn_depth: Maximum depth for recursive spawning (default 2).

    Returns:
        The sub-agent's final response as text.
    """
    from agentsx.agent.subagent import SubAgentConfig  # noqa: PLC0415

    resolved_model = model_name or "gpt-4o"

    config = SubAgentConfig(
        model_name=resolved_model,
        system_prompt=system_prompt,
        max_steps=max_steps,
        timeout=timeout,
        max_spawn_depth=max_spawn_depth,
    )

    orchestra = _get_orchestra()
    try:
        result: str = await orchestra.spawn(config, prompt)
        return result
    except (RuntimeError, TimeoutError) as exc:
        return f"Sub-agent error: {exc}"
