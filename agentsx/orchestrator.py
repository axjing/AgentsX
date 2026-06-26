"""Orchestrator — sub-agent lifecycle management.

Manages spawning, tracking, and limiting concurrent sub-agents.
The parent agent interacts with sub-agents exclusively through the
``spawn_agent`` tool, which delegates to the orchestrator.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from agentsx.agent.subagent import SubAgentConfig, SubAgentRuntime


@dataclass
class SubAgentRecord:
    """Tracks a spawned sub-agent."""

    runtime: SubAgentRuntime
    spawned_at: float
    prompt: str
    depth: int
    result: str | None = None
    error: str | None = None


class Orchestrator:
    """Manages sub-agent lifecycles with resource limits.

    Usage::

        orchestra = Orchestrator(max_active=5)
        result = await orchestra.spawn(
            SubAgentConfig(model_name="gpt-4o"),
            "Read the config file",
        )
    """

    def __init__(
        self,
        max_active: int = 5,
        max_spawn_depth: int = 2,
    ) -> None:
        self._max_active = max_active
        self._max_spawn_depth = max_spawn_depth
        self._agents: dict[str, SubAgentRecord] = {}

    @property
    def max_active(self) -> int:
        return self._max_active

    @property
    def max_spawn_depth(self) -> int:
        return self._max_spawn_depth

    async def spawn(
        self,
        config: SubAgentConfig,
        prompt: str,
        current_depth: int = 0,
        **kwargs: Any,  # noqa: ARG002
    ) -> str:
        """Spawn a sub-agent and wait for its result.

        Args:
            config: Sub-agent configuration (model, tools, etc.).
            prompt: The task prompt for the sub-agent.
            current_depth: Current recursion depth.

        Returns:
            The sub-agent's final response text.

        Raises:
            RuntimeError: If the maximum number of active agents is reached.
            RuntimeError: If maximum spawn depth is exceeded.
            TimeoutError: If execution exceeds *config.timeout* seconds.
        """
        if len(self._agents) >= self._max_active:
            msg = (
                f"Maximum active sub-agents ({self._max_active}) reached. "
                "Wait for some to complete before spawning more."
            )
            raise RuntimeError(msg)

        if config.current_depth >= self._max_spawn_depth:
            msg = (
                f"Maximum spawn depth ({self._max_spawn_depth}) reached. "
                "Cannot spawn nested sub-agents beyond this depth."
            )
            raise RuntimeError(msg)

        runtime = SubAgentRuntime(config, spawn_depth=config.current_depth)
        record = SubAgentRecord(
            runtime=runtime,
            spawned_at=time.time(),
            prompt=prompt,
            depth=config.current_depth,
        )
        self._agents[runtime.id] = record

        try:
            result = await _run_with_timeout(runtime, prompt, config.timeout)
            record.result = result
            return result
        except TimeoutError:
            record.error = f"Timed out after {config.timeout}s"
            raise
        except Exception as exc:
            record.error = str(exc)
            raise
        finally:
            self._agents.pop(runtime.id, None)

    def list_active(self) -> list[dict[str, object]]:
        """Return metadata for all currently active sub-agents."""
        return [
            {
                "id": rec.runtime.id,
                "model": rec.runtime.messages[0].content
                if rec.runtime.messages
                else "",
                "spawned_at": rec.spawned_at,
                "prompt": rec.prompt,
                "depth": rec.depth,
                "status": "running" if rec.result is None else "done",
            }
            for rec in self._agents.values()
        ]


async def _run_with_timeout(
    runtime: SubAgentRuntime,
    prompt: str,
    timeout: int,
) -> str:
    """Run a sub-agent with a wall-clock timeout.

    Uses ``asyncio.wait_for`` to enforce the timeout.
    """
    import asyncio  # noqa: PLC0415

    try:
        return await asyncio.wait_for(runtime.run(prompt), timeout=timeout)
    except asyncio.TimeoutError:
        raise TimeoutError(f"Sub-agent timed out after {timeout}s") from None
