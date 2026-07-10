"""OpenAI / Azure OpenAI provider implementation."""

from collections.abc import AsyncIterator
from typing import Any

import httpx

from agentsx.config import get_settings
from agentsx.core.errors import ProviderError
from agentsx.core.types import AgentMessage, StreamEvent
from agentsx.provider import Model, Provider, register_provider
from agentsx.provider.transport import OpenAITransport


class OpenAIProvider(Provider):
    """Provider for OpenAI-compatible chat completion APIs.

    Supports both official OpenAI and Azure OpenAI endpoints.
    Uses ``OpenAITransport`` for format conversion and stream parsing.
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

    async def stream(
        self,
        messages: list[AgentMessage],
    ) -> AsyncIterator[StreamEvent]:
        settings = get_settings()
        profile = self.profile
        api_key = self._api_key or settings.openai_api_key or settings.api_key
        api_base = (
            self._api_base
            or settings.openai_api_base
            or (profile.base_url if profile else "https://api.openai.com/v1")
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
        if profile:
            headers.update(profile.extra_headers)

        formatted = self.format_messages(messages)
        kwargs = self.transport.build_kwargs(
            messages=formatted,
            tools=self.tools.to_openai_tools() if self.tools else None,
            max_tokens=self.model.max_tokens,
            model=self.model.id,
        )
        kwargs["headers"] = headers

        url = f"{api_base.rstrip('/')}/chat/completions"
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                async with client.stream(
                    "POST",
                    url,
                    json=kwargs,
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        raise ProviderError(
                            f"OpenAI API error (HTTP {response.status_code}): "
                            f"{body.decode(errors='replace')}",
                            status_code=response.status_code,
                        )
                    async for event in self.transport.parse_stream(response):
                        yield event

            except httpx.RequestError as exc:
                raise ProviderError(
                    f"OpenAI request failed: {exc}",
                ) from exc

    def format_messages(self, messages: list[AgentMessage]) -> list[dict[str, Any]]:
        """Convert AgentMessages to OpenAI message format.

        Delegates to the configured ``OpenAITransport``.

        Args:
            messages: Conversation history in AgentMessage format.

        Returns:
            A list of dicts in OpenAI message wire format.
        """
        assert self.transport is not None
        return self.transport.format_messages(messages)


register_provider("openai", OpenAIProvider)
