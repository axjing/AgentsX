"""Anthropic Claude provider implementation."""

from collections.abc import AsyncIterator
from typing import Any

import httpx

from agentsx.config import get_settings
from agentsx.core.errors import ProviderError
from agentsx.core.types import AgentMessage, MessageRole, StreamEvent
from agentsx.provider import Model, Provider, register_provider
from agentsx.provider.transport import AnthropicTransport


class AnthropicProvider(Provider):
    """Provider for Anthropic Claude API.

    Uses ``AnthropicTransport`` for format conversion and stream parsing.
    Handles both ``text_delta`` and ``input_json_delta`` SSE events
    to support tool use streaming.
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
        self.transport = AnthropicTransport()

    def _extract_system(self, messages: list[AgentMessage]) -> str:
        """Extract the system prompt from the message list.

        Args:
            messages: Conversation history.

        Returns:
            System prompt string, or empty string if none.
        """
        if messages and messages[0].role == MessageRole.SYSTEM:
            return messages[0].content
        return ""

    async def stream(
        self,
        messages: list[AgentMessage],
    ) -> AsyncIterator[StreamEvent]:
        settings = get_settings()
        profile = self.profile
        api_key = self._api_key or settings.anthropic_api_key or settings.api_key
        api_base = (
            self._api_base
            or settings.anthropic_api_base
            or (profile.base_url if profile else "https://api.anthropic.com/v1")
        )
        if not api_key:
            raise ProviderError(
                "ANTHROPIC_API_KEY is not set. "
                "Set the AGENTSX_ANTHROPIC_API_KEY environment variable.",
            )

        headers: dict[str, str] = {
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "anthropic-version": (
                profile.anthropic_version if profile else "2023-06-01"
            ),
        }
        if profile:
            headers.update(profile.extra_headers)

        system_prompt = self._extract_system(messages)
        assert self.transport is not None
        formatted = self.transport.format_messages(messages)
        kwargs = self.transport.build_kwargs(
            messages=formatted,
            tools=self.tools.to_anthropic_tools() if self.tools else None,
            max_tokens=self.model.max_tokens,
            model=self.model.id,
            system=system_prompt,
        )
        kwargs["headers"] = headers

        url = f"{api_base.rstrip('/')}/messages"
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
                            f"Anthropic API error (HTTP {response.status_code}): "
                            f"{body.decode(errors='replace')}",
                            status_code=response.status_code,
                        )
                    async for event in self.transport.parse_stream(response):
                        yield event

            except httpx.RequestError as exc:
                raise ProviderError(
                    f"Anthropic request failed: {exc}",
                ) from exc

    def format_messages(self, messages: list[AgentMessage]) -> list[dict[str, Any]]:
        """Convert AgentMessages to Anthropic message format.

        Delegates to the configured ``AnthropicTransport``.

        Args:
            messages: Conversation history in AgentMessage format.

        Returns:
            A list of dicts in Anthropic message wire format (excluding
            the system message).
        """
        assert self.transport is not None
        return self.transport.format_messages(messages)


register_provider("anthropic", AnthropicProvider)
