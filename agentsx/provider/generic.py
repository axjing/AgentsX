"""Generic OpenAI-compatible provider.

Supports any OpenAI-compatible API endpoint with configurable
base URL and API key. This covers most major providers:

- Google Gemini (https://generativelanguage.googleapis.com/v1beta/openai/)
- DeepSeek (https://api.deepseek.com/v1)
- Groq (https://api.groq.com/openai/v1)
- OpenRouter (https://openrouter.ai/api/v1)
- Ollama (http://localhost:11434/v1)
- Together AI (https://api.together.xyz/v1)
- vLLM, LM Studio, and other local servers
"""

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

# Provider-specific API key and base URL mappings
_PROVIDER_KEYS: dict[str, tuple[str, str]] = {
    "gemini": ("gemini_api_key", ""),
    "deepseek": ("deepseek_api_key", ""),
    "groq": ("groq_api_key", ""),
    "openrouter": ("openrouter_api_key", ""),
    "ollama": ("", "ollama_api_base"),
    "vllm": ("vllm_api_key", "vllm_api_base"),
    "sglang": ("sglang_api_key", "sglang_api_base"),
    "custom": ("custom_api_key", "custom_api_base"),
}

# Default base URLs for providers
_PROVIDER_BASE_URLS: dict[str, str] = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "deepseek": "https://api.deepseek.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
    "vllm": "http://localhost:8000/v1",
    "sglang": "http://localhost:30000/v1",
    "custom": "",
}


class GenericProvider(Provider):
    """Generic OpenAI-compatible provider.

    Connects to any OpenAI-compatible API endpoint. The provider
    is configured via settings or explicit constructor arguments.

    Usage::

        # Via create_provider (uses settings)
        provider = create_provider("gemini/gemini-2.0-flash")
        provider = create_provider("deepseek/deepseek-chat")
        provider = create_provider("ollama/llama3")

        # Explicit configuration
        provider = GenericProvider(
            model=Model(id="my-model", provider_name="custom"),
            api_key="sk-...",
            api_base="https://api.example.com/v1",
        )
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

    def _resolve_api_key(self) -> str:
        settings = get_settings()
        if self._api_key:
            return self._api_key
        provider_name = self.model.provider_name
        key_attr, _ = _PROVIDER_KEYS.get(provider_name, ("", ""))
        if key_attr:
            key = getattr(settings, key_attr, "")
            if key:
                return key
        # Fallback to generic API key
        return settings.api_key

    def _resolve_api_base(self) -> str:
        settings = get_settings()
        if self._api_base:
            return self._api_base
        provider_name = self.model.provider_name
        _, base_attr = _PROVIDER_KEYS.get(provider_name, ("", ""))
        if base_attr:
            base = getattr(settings, base_attr, "")
            if base:
                return base
        # Use default or fallback
        return _PROVIDER_BASE_URLS.get(
            provider_name,
            settings.api_base or "https://api.openai.com/v1",
        )

    async def stream(
        self,
        messages: list[AgentMessage],
    ) -> AsyncIterator[StreamEvent]:
        api_key = self._resolve_api_key()
        api_base = self._resolve_api_base()

        if not api_key and self.model.provider_name != "ollama":
            raise ProviderError(
                f"API key not set for {self.model.provider_name}. "
                f"Set the appropriate AGENTSX_*_API_KEY environment variable."
            )

        headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if api_key:
            if self.model.provider_name == "openrouter":
                headers["HTTP-Referer"] = "https://agentsx.local"
                headers["X-Title"] = "AgentsX"
            headers["Authorization"] = f"Bearer {api_key}"

        payload: dict[str, Any] = {
            "model": self.model.id,
            "messages": self.format_messages(messages),
            "stream": True,
            "max_tokens": self.model.max_tokens,
        }
        if self.tools is not None:
            payload["tools"] = self.tools.to_openai_tools()

        # Provider-specific overrides
        if self.model.provider_name == "deepseek":
            payload["max_tokens"] = self.model.max_tokens or 8192

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
                            f"{self.model.provider_name} API error "
                            f"(HTTP {response.status_code}): "
                            f"{body.decode(errors='replace')}"
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
                    f"{self.model.provider_name} request failed: {exc}",
                ) from exc

    def format_messages(self, messages: list[AgentMessage]) -> list[dict[str, Any]]:
        """Convert AgentMessages to OpenAI-compatible message format."""
        result: list[dict[str, Any]] = []
        for msg in messages:
            converted = msg.convert_to_provider("openai")
            result.append(converted)
        return result


def _parse_sse_chunk(data: str) -> dict[str, Any] | None:
    """Parse a single SSE data: line from OpenAI-compatible API."""
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


# Register all generic providers
register_provider("gemini", GenericProvider)
register_provider("deepseek", GenericProvider)
register_provider("groq", GenericProvider)
register_provider("openrouter", GenericProvider)
register_provider("ollama", GenericProvider)
register_provider("vllm", GenericProvider)
register_provider("sglang", GenericProvider)
register_provider("custom", GenericProvider)
