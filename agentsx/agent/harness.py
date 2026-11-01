"""Stateful agent harness wrapping run_agent_loop().

AgentHarness owns the transcript, cancellation, event listeners,
and message queues (steering + follow-up).  Execution is delegated
to the pure ``run_agent_loop()`` async generator.

Supports optional context compaction via a ``SessionStore``:
when a store is attached, ``compact()`` triggers the store's
compaction entry recording and replaces in-memory messages.
"""

import logging
from collections import deque
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from agentsx.agent.loop import ApprovalCallback, run_agent_loop
from agentsx.context.compaction import compact_messages, should_compact
from agentsx.extensions.api import ExtensionAPI
from agentsx.protocol.errors import SessionError
from agentsx.protocol.events import AgentEvent, ModelResponseEvent
from agentsx.protocol.messages import AgentMessage, MessageRole
from agentsx.provider import Provider
from agentsx.security.policy import ExecutionPolicy
from agentsx.session.protocol import SessionBackend
from agentsx.tools import ToolRegistry

EventListener = Callable[[AgentEvent], None]
"""Callback signature for event subscribers."""

logger = logging.getLogger(__name__)


class AgentHarness:
    """Stateful facade that manages an agent session.

    Owns message history, event subscribers, cancellation state,
    and two message queues:

    - **Follow-up queue**: drained after the current turn completes,
      each item triggers a new agent loop run.
    - **Steer queue**: processed mid-loop for interrupt-and-redirect
      (passed to ``run_agent_loop()``).

    Usage::

        harness = AgentHarness(provider=provider)
        harness.subscribe(lambda e: print(e))
        async for event in harness.prompt("Hello"):
            ...
    """

    def __init__(
        self,
        provider: Provider,
        system_prompt: str | None = None,
        tools: ToolRegistry | None = None,
        policy: ExecutionPolicy | None = None,
        extensions: ExtensionAPI | None = None,
        max_steps: int | None = None,
        session_store: SessionBackend | None = None,
        session_id: str = "",
        approval_callback: ApprovalCallback | None = None,
    ) -> None:
        """Initialise the harness.

        Args:
            provider: LLM provider instance.
            system_prompt: Optional system prompt prepended to messages.
            tools: Optional tool registry for tool-call execution.
            policy: Optional security policy for tool-call gating.
            extensions: Optional extension API for lifecycle hooks.
            max_steps: Maximum tool-calling iterations per turn.
            session_store: Optional session store for compaction.
            session_id: Session ID for compaction entry recording.
            approval_callback: Optional async callback for tool execution confirmation.
        """
        self._provider = provider
        self._system_prompt = system_prompt
        self._tools = tools
        self._policy = policy
        self._extensions = extensions
        self._max_steps = max_steps
        self._session_store = session_store
        self._session_id = session_id
        self._approval_callback = approval_callback
        self._messages: list[AgentMessage] = []
        self._cancelled = False
        self._listeners: list[EventListener] = []
        self._follow_up_queue: deque[str] = deque()
        self._steer_queue: deque[str] = deque()
        self._total_prompt_tokens: int = 0
        self._total_completion_tokens: int = 0
        self._total_cached_tokens: int = 0

        effective_system_prompt = system_prompt or ""
        memory_content = self._load_persistent_memory()
        if memory_content:
            if effective_system_prompt:
                effective_system_prompt += f"\n\n{memory_content}"
            else:
                effective_system_prompt = memory_content

        if effective_system_prompt:
            self._messages.append(
                AgentMessage(role=MessageRole.SYSTEM, content=effective_system_prompt),
            )

    @staticmethod
    def _load_persistent_memory() -> str:
        """Load persistent guidelines from project and global memory.md."""
        candidates = [
            (Path.cwd() / ".agentsx" / "memory.md", "Project Memory & Learned Rules"),
            (Path.home() / ".agentsx" / "memory.md", "Global Learned Rules"),
        ]
        snippets: list[str] = []
        seen_files: set[Path] = set()
        for p, title in candidates:
            try:
                resolved = p.resolve()
                if resolved in seen_files:
                    continue
                seen_files.add(resolved)
                if p.is_file():
                    text = p.read_text(encoding="utf-8").strip()
                    if text:
                        snippets.append(f"## {title}:\n{text}")
            except OSError:
                continue
        return "\n\n".join(snippets)

    # -- Properties --

    @property
    def provider(self) -> Provider:
        """The LLM provider for this harness."""
        return self._provider

    @provider.setter
    def provider(self, new_provider: Provider) -> None:
        """Hot-swap the LLM provider for subsequent turns."""
        self._provider = new_provider

    @property
    def messages(self) -> list[AgentMessage]:
        """Read-only copy of the current message history."""
        return list(self._messages)

    @property
    def token_stats(self) -> dict[str, int]:
        """Cumulative token metrics for the current session."""
        return {
            "prompt_tokens": self._total_prompt_tokens,
            "completion_tokens": self._total_completion_tokens,
            "total_tokens": self._total_prompt_tokens + self._total_completion_tokens,
            "cached_tokens": self._total_cached_tokens,
        }

    # -- Public API --

    def load_messages(self, messages: list[AgentMessage]) -> None:
        """Replace current message history with the given messages."""
        self._messages.clear()
        self._messages.extend(messages)

    async def prompt(
        self,
        user_input: str | AgentMessage,
        *,
        timeout: float = 0,
    ) -> AsyncIterator[AgentEvent]:
        """Process a user message through the agent loop.

        Appends the user message, runs the loop, dispatches events
        to subscribers, then drains the follow-up queue as additional
        turns.

        Args:
            user_input: The user's message text or AgentMessage.
            timeout: Wall-clock timeout in seconds (0 = disabled).

        Yields:
            AgentEvent items from the agent loop.
        """
        self._cancelled = False
        if isinstance(user_input, AgentMessage):
            self._messages.append(user_input)
        else:
            self._messages.append(
                AgentMessage(role=MessageRole.USER, content=user_input),
            )

        async for event in self._run_loop(timeout=timeout):
            yield event

        # Drain follow-up queue after the main loop completes
        while self._follow_up_queue and not self._cancelled:
            follow_up_msg = self._follow_up_queue.popleft()
            self._messages.append(
                AgentMessage(role=MessageRole.USER, content=follow_up_msg),
            )
            async for event in self._run_loop(timeout=timeout):
                yield event

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        """Register an event listener.

        Args:
            listener: Callback invoked for each event dispatched
                during prompt execution.

        Returns:
            An unsubscribe callback that removes the listener.
        """
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def queue_follow_up(self, content: str) -> None:
        """Queue a message to be processed after the current turn.

        Args:
            content: The follow-up message text.
        """
        self._follow_up_queue.append(content)

    def queue_steering(self, content: str) -> None:
        """Queue a message for mid-run injection on the next turn.

        Items are consumed by ``run_agent_loop()`` as additional
        user messages between loop iterations.

        Args:
            content: The steering message text.
        """
        self._steer_queue.append(content)

    def cancel(self) -> None:
        """Signal cancellation.

        The current prompt call will stop after the current step
        completes and will not process any queued follow-up messages.
        """
        self._cancelled = True

    def compact(self, force: bool = False) -> tuple[str, int]:
        """Trigger context compaction on the current message list.

        If a session store is attached, records the compaction entry.

        Args:
            force: If True, skip the ``should_compact()`` threshold check.

        Returns:
            (status_message, new_message_count).
        """
        if not force and not should_compact(self._messages):
            return (
                f"No compaction needed ({len(self._messages)} messages). "
                "Use compact(force=True) to override.",
                len(self._messages),
            )

        old_count = len(self._messages)
        compacted = compact_messages(self._messages)
        new_count = len(compacted)

        if new_count >= old_count:
            return "No messages could be compacted.", old_count

        # Record compaction entry if session store is attached
        if self._session_store and self._session_id:
            replaced_ids = [m.id for m in self._messages[: old_count - new_count + 1]]
            summary = (
                compacted[1].content if len(compacted) > 1 else "Context compacted"
            )
            try:
                self._session_store.append_compaction_entry(
                    self._session_id,
                    replaces_ids=replaced_ids,
                    summary=summary,
                )
            except SessionError:
                pass

        self._messages.clear()
        self._messages.extend(compacted)

        return (
            f"Compacted: {old_count} → {new_count} messages "
            f"(saved {old_count - new_count})",
            new_count,
        )

    def clear_history(self) -> None:
        """Clear message history, preserving the system prompt.

        Also clears both the follow-up and steer queues.
        """
        has_system = bool(
            self._messages and self._messages[0].role == MessageRole.SYSTEM,
        )
        system = self._messages[0] if has_system else None
        self._messages.clear()
        if system:
            self._messages.append(system)
        self._follow_up_queue.clear()
        self._steer_queue.clear()
        self._total_prompt_tokens = 0
        self._total_completion_tokens = 0
        self._total_cached_tokens = 0

    # -- Internals --

    async def _run_loop(self, timeout: float = 0) -> AsyncIterator[AgentEvent]:
        """Run the agent loop and dispatch events to subscribers.

        Args:
            timeout: Wall-clock timeout in seconds (0 = disabled).

        Yields:
            AgentEvent items from the agent loop.
        """
        async for event in run_agent_loop(
            self._provider,
            self._messages,
            max_steps=self._max_steps,
            tools=self._tools,
            policy=self._policy,
            extensions=self._extensions,
            timeout=timeout,
            steer_queue=self._steer_queue,
            approval_callback=self._approval_callback,
        ):
            if self._cancelled:
                break
            if isinstance(event, ModelResponseEvent) and event.usage:
                self._total_prompt_tokens += event.usage.get("prompt_tokens", 0)
                self._total_completion_tokens += event.usage.get("completion_tokens", 0)
                self._total_cached_tokens += event.usage.get("cached_tokens", 0)

            for listener in self._listeners:
                try:
                    listener(event)
                except Exception:  # noqa: BLE001
                    logger.exception("Event listener error")
            yield event
