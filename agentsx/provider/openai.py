"""OpenAI / Azure OpenAI provider implementation."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from agentsx.config import get_settings
from agentsx.core.errors import ProviderError
from agentsx.core.types import (
    AgentMessage,
    MessageRole,
    StreamEvent,
    TextStreamEvent,
    ToolCall,
    ToolCallStreamEvent,
)
from agentsx.provider import Provider, register_provider


class OpenAIProvider(Provider):
    """Provider for OpenAI-compatible chat completion APIs.

    Supports both official OpenAI and Azure OpenAI endpoints.
    Handles text streaming and tool call detection from SSE chunks.
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
        api_key = self._api_key or settings.openai_api_key or settings.api_key
        api_base = (
            self._api_base or settings.openai_api_base or "https://api.openai.com/v1"
        )
        if not api_key:
            raise ProviderError(
                "OPENAI_API_KEY is not set. "
                "Set the AGENTSX_OPENAI_API_KEY environment variable.",
            )

        headers: dict[str, str] = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model.id,
            "messages": self.format_messages(messages),
            "stream": True,
            "max_tokens": self.model.max_tokens,
        }
        if self.tools is not None:
            payload["tools"] = self.tools.to_openai_tools()

        tool_deltas: dict[int, dict[str, str]] = {}

        url = f"{api_base.rstrip('/')}/chat/completions"
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
                            f"OpenAI API error (HTTP {response.status_code}): "
                            f"{body.decode(errors='replace')}",
                        )
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line.removeprefix("data: ").strip()
                        if data in ("", "[DONE]"):
                            continue

                        parsed = _parse_sse_chunk(data)
                        if parsed is None:
                            continue

                        text = parsed.get("text")
                        if text:
                            yield TextStreamEvent(text=text)

                        tc_list = parsed.get("tool_calls")
                        if tc_list:
                            for tc in tc_list:
                                idx = tc.get("index", 0)
                                if idx not in tool_deltas:
                                    tool_deltas[idx] = {
                                        "id": "",
                                        "name": "",
                                        "arguments": "",
                                    }
                                entry = tool_deltas[idx]
                                if "id" in tc and tc["id"]:
                                    entry["id"] = tc["id"]
                                fn = tc.get("function")
                                if isinstance(fn, dict):
                                    if "name" in fn and fn["name"]:
                                        entry["name"] = fn["name"]
                                    if "arguments" in fn and fn["arguments"]:
                                        entry["arguments"] += fn["arguments"]

                        finish = parsed.get("finish_reason")
                        if finish == "tool_calls" and tool_deltas:
                            for entry in tool_deltas.values():
                                try:
                                    args = (
                                        json.loads(entry["arguments"])
                                        if entry["arguments"]
                                        else {}
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
                            tool_deltas.clear()

            except httpx.RequestError as exc:
                raise ProviderError(
                    f"OpenAI request failed: {exc}",
                ) from exc

    def format_messages(self, messages: list[AgentMessage]) -> list[dict[str, Any]]:
        """Convert AgentMessages to OpenAI message format."""
        result: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == MessageRole.TOOL:
                result.append(
                    {
                        "role": "tool",
                        "content": msg.content,
                        "tool_call_id": msg.tool_call_id or "",
                    }
                )
            else:
                entry: dict[str, Any] = {"role": msg.role.value, "content": msg.content}
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                if msg.name:
                    entry["name"] = msg.name
                result.append(entry)
        return result


def _parse_sse_chunk(data: str) -> dict[str, Any] | None:
    """Parse a single SSE ``data:`` line from OpenAI."""
    try:
        obj: dict[str, Any] = json.loads(data)
    except json.JSONDecodeError:
        return None

    choices = obj.get("choices")
    if not choices or not isinstance(choices, list) or not choices:
        return None

    first = choices[0]
    if not isinstance(first, dict):
        return None

    result: dict[str, Any] = {}

    delta = first.get("delta", {})
    if isinstance(delta, dict):
        content = delta.get("content")
        if isinstance(content, str):
            result["text"] = content

        tc_raw = delta.get("tool_calls")
        if tc_raw and isinstance(tc_raw, list):
            result["tool_calls"] = tc_raw

    finish = first.get("finish_reason")
    if isinstance(finish, str) and finish:
        result["finish_reason"] = finish

    return result


register_provider("openai", OpenAIProvider)
