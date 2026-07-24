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

Uses ``OpenAITransport`` for format conversion and stream parsing.
"""

from collections.abc import AsyncIterator
from typing import Any

import httpx

from agentsx.config import get_settings
from agentsx.protocol.errors import ProviderError
from agentsx.protocol.events import AgentMessage, StreamEvent
from agentsx.provider import Model, Provider, get_profile, register_provider
from agentsx.provider.transport import OpenAITransport


class GenericProvider(Provider):
    """Generic OpenAI-compatible provider.

    Connects to any OpenAI-compatible API endpoint. The provider
    is configured via settings or explicit constructor arguments.
    Uses ``OpenAITransport`` for format conversion and stream parsing.

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
        model: Model,
        api_key: str | None = None,
        api_base: str | None = None,
        **kwargs: object,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._api_base = api_base
        self.transport = OpenAITransport()

    def _resolve_api_key(self) -> str:
        settings = get_settings()
        if self._api_key:
            return self._api_key
        provider_name = self.model.provider_name
        profile = get_profile(provider_name)
        if profile and profile.env_api_key:
            env_key = profile.env_api_key.removeprefix("AGENTSX_").lower()
            key_val = getattr(settings, env_key, "")
            if key_val:
                return key_val
        return settings.api_key

    def _resolve_api_base(self) -> str:
        settings = get_settings()
        if self._api_base:
            return self._api_base
        provider_name = self.model.provider_name
        profile = get_profile(provider_name)
        if profile and profile.env_api_base:
            env_base = profile.env_api_base.removeprefix("AGENTSX_").lower()
            base_val = getattr(settings, env_base, "")
            if base_val:
                return base_val
        if profile and profile.base_url:
            return profile.base_url
        return settings.api_base or "https://api.openai.com/v1"

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
        profile = get_profile(self.model.provider_name)
        if profile:
            headers.update(profile.extra_headers)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        assert self.transport is not None
        formatted = self.transport.format_messages(messages)
        kwargs = self.transport.build_kwargs(
            messages=formatted,
            tools=self.tools.to_openai_tools() if self.tools else None,
            max_tokens=self.model.max_tokens,
            model=self.model.id,
        )
        # Provider-specific overrides
        if self.model.provider_name == "deepseek":
            kwargs["max_tokens"] = self.model.max_tokens or 8192

        url = f"{api_base.rstrip('/')}/chat/completions"
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                async with client.stream(
                    "POST",
                    url,
                    json=kwargs,
                    headers=headers,
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        raise ProviderError(
                            f"{self.model.provider_name} API error "
                            f"(HTTP {response.status_code}): "
                            f"{body.decode(errors='replace')}",
                            status_code=response.status_code,
                        )
                    async for event in self.transport.parse_stream(response):
                        yield event

            except httpx.RequestError as exc:
                raise ProviderError(
                    f"{self.model.provider_name} request failed: {exc}",
                ) from exc

    def format_messages(self, messages: list[AgentMessage]) -> list[dict[str, Any]]:
        """Convert AgentMessages to OpenAI-compatible message format.

        Delegates to the configured ``OpenAITransport``.

        Args:
            messages: Conversation history in AgentMessage format.

        Returns:
            A list of dicts in OpenAI message wire format.
        """
        assert self.transport is not None
        return self.transport.format_messages(messages)


# Register all generic providers
register_provider("gemini", GenericProvider)
register_provider("deepseek", GenericProvider)
register_provider("groq", GenericProvider)
register_provider("openrouter", GenericProvider)
register_provider("ollama", GenericProvider)
register_provider("vllm", GenericProvider)
register_provider("sglang", GenericProvider)
register_provider("qwen", GenericProvider)
register_provider("custom", GenericProvider)
