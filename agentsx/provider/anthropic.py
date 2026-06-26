"""Anthropic Claude provider implementation."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from agentsx.config import get_settings
from agentsx.core.errors import ProviderError
from agentsx.core.types import (
    AgentMessage,
    StreamEvent,
    TextStreamEvent,
    ToolCall,
    ToolCallStreamEvent,
)
from agentsx.provider import Provider, register_provider


class AnthropicProvider(Provider):
    """Provider for Anthropic Claude API.

    Handles both ``text_delta`` and ``input_json_delta`` SSE events
    to support tool use streaming.
    """

    def __init__(
        self,
        model: Any,
        api_key: str | None = None,
        api_base: str | None = None,
        **kwargs: object,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._api_base = api_base

    async def stream(
        self,
        messages: list[AgentMessage],
    ) -> AsyncIterator[StreamEvent]:
        settings = get_settings()
        api_key = self._api_key or settings.anthropic_api_key or settings.api_key
        api_base = (
            self._api_base
            or settings.anthropic_api_base
            or "https://api.anthropic.com/v1"
        )
        if not api_key:
            raise ProviderError(
                "ANTHROPIC_API_KEY is not set. "
                "Set the AGENTSX_ANTHROPIC_API_KEY environment variable.",
            )

        headers: dict[str, str] = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model.id,
            "messages": self.format_messages(messages),
            "stream": True,
            "max_tokens": self.model.max_tokens,
        }
        if self.tools is not None:
            payload["tools"] = self.tools.to_anthropic_tools()

        block_id: str = ""
        block_name: str = ""
        block_args: str = ""

        url = f"{api_base.rstrip('/')}/messages"
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                async with client.stream(
                    "POST",
                    url,
                    json=payload,
                    headers=headers,
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        raise ProviderError(
                            f"Anthropic API error (HTTP {response.status_code}): "
                            f"{body.decode(errors='replace')}",
                        )

                    event_type = ""
                    async for line in response.aiter_lines():
                        if line.startswith("event: "):
                            event_type = line.removeprefix("event: ").strip()
                            continue

                        if not line.startswith("data: "):
                            continue
                        data = line.removeprefix("data: ").strip()
                        if data == "":
                            continue

                        obj: dict[str, Any] = json.loads(data)

                        if event_type == "content_block_start":
                            cb = obj.get("content_block", {})
                            if cb.get("type") == "tool_use":
                                block_id = cb.get("id", "")
                                block_name = cb.get("name", "")
                                block_args = ""
                            continue

                        if event_type == "content_block_delta":
                            delta = obj.get("delta", {})
                            delta_type = delta.get("type")
                            if delta_type == "text_delta":
                                text = delta.get("text", "")
                                yield TextStreamEvent(text=text)
                            elif delta_type == "input_json_delta":
                                block_args += delta.get("partial_json", "")
                            continue

                        if event_type == "content_block_stop":
                            if block_id and block_name:
                                try:
                                    args = json.loads(block_args) if block_args else {}
                                except json.JSONDecodeError:
                                    args = {}
                                yield ToolCallStreamEvent(
                                    tool_call=ToolCall(
                                        id=block_id,
                                        name=block_name,
                                        arguments=args,
                                    ),
                                )
                                block_id = ""
                                block_name = ""
                                block_args = ""
                            continue

            except httpx.RequestError as exc:
                raise ProviderError(
                    f"Anthropic request failed: {exc}",
                ) from exc

    def format_messages(self, messages: list[AgentMessage]) -> list[dict[str, Any]]:
        """Convert AgentMessages to Anthropic message format."""
        result: list[dict[str, Any]] = []
        for msg in messages:
            converted = msg.convert_to_provider("anthropic")
            result.append(converted)
        return result


register_provider("anthropic", AnthropicProvider)
