"""Provider transport abstraction layer.

Separates format-conversion from orchestration (credential resolution,
client construction, retry loops, streaming loops).

Use ``ProviderTransport`` subclasses to convert ``AgentMessage`` lists
to provider-native dicts, build request kwargs, and parse raw streaming
responses back into ``StreamEvent`` objects.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from agentsx.core.types import (
    AgentMessage,
    MessageRole,
    StreamEvent,
    TextStreamEvent,
    ToolCall,
    ToolCallStreamEvent,
)


class ProviderTransport(ABC):
    """Abstract base for provider transport adapters.

    Owns ONLY format conversion — message formatting, kwargs building,
    and stream parsing. Credential resolution, client setup, and retry
    logic remain in the Provider layer.
    """

    @abstractmethod
    def format_messages(self, messages: list[AgentMessage]) -> list[dict[str, Any]]:
        """Convert internal ``AgentMessage`` objects to provider-native dicts.

        Args:
            messages: Conversation history in internal format.

        Returns:
            A list of dicts in the provider's message wire format.
        """

    @abstractmethod
    def build_kwargs(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        **extra: Any,
    ) -> dict[str, Any]:
        """Build the final API request kwargs dict.

        Args:
            messages: Already-formatted message dicts from
                :meth:`format_messages`.
            tools: Provider-native tool schemas, or ``None``.
            max_tokens: Maximum output token budget.
            **extra: Provider-specific extras (model name, system prompt,
                temperature, etc.).

        Returns:
            A dict suitable for passing to the HTTP client as ``json=``.
        """

    @abstractmethod
    def parse_stream(self, response: Any) -> AsyncIterator[StreamEvent]:
        """Parse a raw provider streaming response into ``StreamEvent`` objects.

        Args:
            response: The raw streaming response from the provider's HTTP
                client (type varies by provider; ``Any`` is unavoidable).

        Yields:
            ``TextStreamEvent`` for text tokens and
            ``ToolCallStreamEvent`` for completed tool calls.
        """


async def _openai_parse_stream_impl(
    response: Any,
) -> AsyncIterator[StreamEvent]:
    """Async generator: parse OpenAI SSE response into ``StreamEvent`` objects."""
    import json

    tool_deltas: dict[int, dict[str, str]] = {}

    async for line in response.aiter_lines():
        if not line.startswith("data: "):
            continue
        data = line.removeprefix("data: ").strip()
        if data in ("", "[DONE]"):
            continue

        try:
            obj: dict[str, Any] = json.loads(data)
        except json.JSONDecodeError:
            continue

        choices = obj.get("choices")
        if not choices or not isinstance(choices, list) or not choices:
            continue

        first = choices[0]
        if not isinstance(first, dict):
            continue

        delta = first.get("delta", {})
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str) and content:
                yield TextStreamEvent(text=content)

            tc_raw = delta.get("tool_calls")
            if tc_raw and isinstance(tc_raw, list):
                for tc_delta in tc_raw:
                    idx = tc_delta.get("index", 0)
                    if idx not in tool_deltas:
                        tool_deltas[idx] = {
                            "id": "",
                            "name": "",
                            "arguments": "",
                        }
                    entry = tool_deltas[idx]
                    if "id" in tc_delta and tc_delta["id"]:
                        entry["id"] = tc_delta["id"]
                    fn = tc_delta.get("function")
                    if isinstance(fn, dict):
                        if "name" in fn and fn["name"]:
                            entry["name"] = fn["name"]
                        if "arguments" in fn and fn["arguments"]:
                            entry["arguments"] += fn["arguments"]

        finish = first.get("finish_reason")
        if finish == "tool_calls" and tool_deltas:
            for entry in tool_deltas.values():
                try:
                    args = json.loads(entry["arguments"]) if entry["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}
                yield ToolCallStreamEvent(
                    tool_call=ToolCall(
                        id=entry["id"],
                        name=entry["name"],
                        arguments=args,
                    ),
                )
            tool_deltas.clear()


async def _anthropic_parse_stream_impl(
    response: Any,
) -> AsyncIterator[StreamEvent]:
    """Async generator: parse Anthropic SSE response into ``StreamEvent`` objects."""
    import json

    event_type = ""
    tool_accumulators: dict[int, dict[str, str]] = {}  # index -> {id, name, input_json}

    async for line in response.aiter_lines():
        if line.startswith("event: "):
            event_type = line.removeprefix("event: ").strip()
            continue

        if not line.startswith("data: "):
            continue
        data = line.removeprefix("data: ").strip()
        if data == "":
            continue

        try:
            obj: dict[str, Any] = json.loads(data)
        except json.JSONDecodeError:
            continue

        if event_type == "content_block_delta":
            delta = obj.get("delta", {})
            delta_type = delta.get("type")
            if delta_type == "text_delta":
                text = delta.get("text", "")
                if text:
                    yield TextStreamEvent(text=text)
            elif delta_type == "input_json_delta":
                partial_json = delta.get("partial_json", "")
                # Accumulate into the active tool's input (identified by the
                # most recently started content-block index).
                index = obj.get("index", 0)
                if index in tool_accumulators:
                    tool_accumulators[index]["input_json"] += partial_json

        elif event_type == "content_block_start":
            content_block = obj.get("content_block", {})
            if content_block.get("type") == "tool_use":
                index = obj.get("index", 0)
                tool_accumulators[index] = {
                    "id": content_block.get("id", ""),
                    "name": content_block.get("name", ""),
                    "input_json": "",
                }

        elif event_type == "content_block_stop":
            # If we have an accumulated tool call, yield it on stop.
            index = obj.get("index", 0)
            if index in tool_accumulators:
                entry = tool_accumulators.pop(index)
                try:
                    args = (
                        json.loads(entry["input_json"]) if entry["input_json"] else {}
                    )
                except json.JSONDecodeError:
                    args = {}
                yield ToolCallStreamEvent(
                    tool_call=ToolCall(
                        id=entry["id"],
                        name=entry["name"],
                        arguments=args,
                    ),
                )


class OpenAITransport(ProviderTransport):
    """Transport adapter for OpenAI-compatible APIs."""

    DEFAULT_MODEL = "gpt-4o"

    def format_messages(self, messages: list[AgentMessage]) -> list[dict[str, Any]]:
        """Convert ``AgentMessage`` objects to OpenAI message format.

        Delegates each message to its ``_to_openai()`` method.

        Args:
            messages: Conversation history in internal format.

        Returns:
            A list of dicts with ``role`` and ``content`` keys (plus
            ``tool_calls`` where applicable).
        """
        result: list[dict[str, Any]] = []
        for msg in messages:
            converted = msg._to_openai()
            result.append(converted)
        return result

    def build_kwargs(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        **extra: Any,
    ) -> dict[str, Any]:
        """Build OpenAI API request kwargs.

        Args:
            messages: Formatted message dicts.
            tools: OpenAI tool schema dicts, or ``None``.
            max_tokens: Maximum output token budget.
            **extra: May include ``model``, ``temperature``, or other
                OpenAI-specific parameters.

        Returns:
            Dict with ``model``, ``messages``, ``max_tokens``, ``stream``,
            and optionally ``tools`` / ``temperature``.
        """
        kwargs: dict[str, Any] = {
            "model": extra.get("model", self.DEFAULT_MODEL),
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
        if "temperature" in extra:
            kwargs["temperature"] = extra["temperature"]
        return kwargs

    def parse_stream(self, response: Any) -> AsyncIterator[StreamEvent]:
        """Parse an OpenAI SSE streaming response into ``StreamEvent`` objects.

        Iterates over the raw httpx streaming response, extracts ``data:``
        lines, and yields ``TextStreamEvent`` for content deltas and
        ``ToolCallStreamEvent`` for completed tool calls.

        Args:
            response: An ``httpx.Response`` object from ``client.stream()``.

        Yields:
            ``TextStreamEvent`` or ``ToolCallStreamEvent`` instances.
        """
        return _openai_parse_stream_impl(response)


class AnthropicTransport(ProviderTransport):
    """Transport adapter for Anthropic Claude API."""

    DEFAULT_MODEL = "claude-sonnet-4-20250514"

    def format_messages(self, messages: list[AgentMessage]) -> list[dict[str, Any]]:
        """Convert ``AgentMessage`` objects to Anthropic message format.

        Extracts the system message separately (returned as part of the
        caller's responsibility via ``build_kwargs(system=...)``). Non-system
        messages are converted via ``_to_anthropic()``.

        Args:
            messages: Conversation history in internal format.

        Returns:
            A list of user/assistant message dicts (system message is
            excluded from the returned list — it goes in ``build_kwargs``).
        """
        result: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                continue
            converted = msg._to_anthropic()
            result.append(converted)
        return result

    def build_kwargs(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        **extra: Any,
    ) -> dict[str, Any]:
        """Build Anthropic API request kwargs.

        Args:
            messages: Formatted message dicts (non-system only).
            tools: Anthropic tool schema dicts, or ``None``.
            max_tokens: Maximum output token budget.
            **extra: May include ``model``, ``system``, or other
                Anthropic-specific parameters.

        Returns:
            Dict with ``model``, ``messages``, ``max_tokens``, and
            optionally ``system`` / ``tools``.
        """
        kwargs: dict[str, Any] = {
            "model": extra.get("model", self.DEFAULT_MODEL),
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if "system" in extra:
            kwargs["system"] = extra["system"]
        if tools:
            kwargs["tools"] = tools
        return kwargs

    def parse_stream(self, response: Any) -> AsyncIterator[StreamEvent]:
        """Parse an Anthropic SSE streaming response into ``StreamEvent`` objects.

        Simplified implementation: yields ``TextStreamEvent`` for text
        deltas. Full tool-call accumulation via ``input_json_delta``
        is complex and can be deferred.

        Args:
            response: An ``httpx.Response`` object from ``client.stream()``.

        Yields:
            ``TextStreamEvent`` for text delta content.
        """
        return _anthropic_parse_stream_impl(response)
