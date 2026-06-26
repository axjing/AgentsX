"""High-level ``Agent`` class wrapping the loop for convenient use."""

from __future__ import annotations

from collections.abc import AsyncIterator

from agentsx.agent.loop import run_agent_loop
from agentsx.config import get_settings
from agentsx.core.types import AgentEvent, AgentMessage, MessageRole
from agentsx.extensions import ExtensionAPI
from agentsx.provider import Provider, create_provider
from agentsx.security import ExecutionPolicy
from agentsx.tools import ToolRegistry


class Agent:
    """Convenience wrapper around ``run_agent_loop()``.

    Usage::

        agent = Agent(model_name="gpt-4o")
        async for event in agent.run("Hello!"):
            print(event)
    """

    def __init__(
        self,
        provider: Provider | None = None,
        model_name: str | None = None,
        system_prompt: str | None = None,
        tools: ToolRegistry | None = None,
        policy: ExecutionPolicy | None = None,
        extensions: ExtensionAPI | None = None,
    ) -> None:
        self._provider = provider
        self._model_name = model_name
        self._system_prompt = system_prompt
        self._tools = tools
        self._policy = policy
        self._extensions = extensions

    async def run(
        self,
        user_input: str,
        max_steps: int | None = None,
        timeout: float = 0,
    ) -> AsyncIterator[AgentEvent]:
        """Process a user message through the agent loop.

        Args:
            user_input: The user's message text.
            max_steps: Optional override for max tool-calling steps.
            timeout: Wall-clock timeout in seconds (0 = disabled).

        Yields:
            ``AgentEvent`` items from the agent loop.
        """
        provider = self._resolve_provider()
        messages = self._build_messages(user_input)
        async for event in run_agent_loop(
            provider,
            messages,
            max_steps,
            tools=self._tools,
            policy=self._policy,
            extensions=self._extensions,
            timeout=timeout,
        ):
            yield event

    # ── Internals ──────────────────────────────────────────────────

    def _resolve_provider(self) -> Provider:
        if self._provider is not None:
            return self._provider
        settings = get_settings()
        return create_provider(
            model_name=self._model_name or settings.model_name,
        )

    def _build_messages(self, user_input: str) -> list[AgentMessage]:
        messages: list[AgentMessage] = []
        prompt = self._system_prompt
        if prompt is None:
            prompt = get_settings().system_prompt
        if prompt:
            messages.append(
                AgentMessage(role=MessageRole.SYSTEM, content=prompt),
            )
        messages.append(
            AgentMessage(role=MessageRole.USER, content=user_input),
        )
        return messages
