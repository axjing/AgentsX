"""High-level `Agent` class wrapping `AgentHarness` for convenient use."""

from collections.abc import AsyncIterator

from agentsx.agent.harness import AgentHarness
from agentsx.config import get_settings
from agentsx.core.types import AgentEvent, AgentMessage, MessageRole
from agentsx.extensions.api import ExtensionAPI
from agentsx.provider import Provider, create_provider
from agentsx.security.policy import ExecutionPolicy
from agentsx.tools import ToolRegistry


class Agent:
    """Convenience wrapper around ``AgentHarness``.

    Maintains an internal message history so that multiple ``run()``
    calls share the same conversation context.

    Usage::

        agent = Agent(model_name="gpt-4o")
        async for event in agent.run("Hello!"):
            print(event)

        async for event in agent.run("What did I just ask?"):
            print(event)  # Agent remembers the first turn.
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
        self._harness: AgentHarness | None = None

    # ── Public API ──────────────────────────────────────────────────

    @property
    def messages(self) -> list[AgentMessage]:
        """Read-only access to the current conversation history."""
        if self._harness is not None:
            return self._harness.messages
        return list(self._messages) if hasattr(self, "_messages") else []

    def clear_history(self) -> None:
        """Clear the conversation history, keeping the system prompt."""
        if self._harness is not None:
            self._harness.clear_history()
        else:
            self._ensure_messages()
            has_system = bool(
                self._messages and self._messages[0].role == MessageRole.SYSTEM,
            )
            system = self._messages[0] if has_system else None
            self._messages.clear()
            if system:
                self._messages.append(system)

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
            `AgentEvent` items from the agent loop.
        """
        harness = self._get_harness(max_steps=max_steps)
        async for event in harness.prompt(user_input, timeout=timeout):
            yield event

    # ── Internals ───────────────────────────────────────────────────

    def _resolve_provider(self) -> Provider:
        if self._provider is not None:
            return self._provider
        settings = get_settings()
        return create_provider(
            model_name=self._model_name or settings.model_name,
        )

    def _build_system_prompt(self) -> str:
        prompt = self._system_prompt
        if prompt is None:
            prompt = get_settings().system_prompt
        return prompt

    def _get_harness(self, max_steps: int | None) -> AgentHarness:
        """Lazy-create the AgentHarness on first run()."""
        if self._harness is None:
            provider = self._resolve_provider()
            settings = get_settings()
            self._harness = AgentHarness(
                provider=provider,
                system_prompt=self._build_system_prompt(),
                tools=self._tools,
                policy=self._policy,
                extensions=self._extensions,
                max_steps=max_steps or settings.max_steps,
            )
        return self._harness

    def _ensure_messages(self) -> list[AgentMessage]:
        """Legacy fallback for direct message access before harness creation."""
        if not hasattr(self, "_messages"):
            system = self._build_system_prompt()
            msgs: list[AgentMessage] = []
            if system:
                msgs.append(
                    AgentMessage(role=MessageRole.SYSTEM, content=system),
                )
            self._messages = msgs
        return self._messages
