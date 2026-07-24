"""Provider abstract base class and Model dataclass."""

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from agentsx.protocol.errors import ProviderError, RetryExhaustedError
from agentsx.protocol.events import (
    AgentMessage,
    RetryEvent,
    StreamEvent,
)
from agentsx.provider.profile import ProviderProfile, get_profile
from agentsx.tools import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class Model:
    """Identifies an LLM model with its provider."""

    id: str
    """Model identifier, e.g. ``"gpt-4o"``, ``"claude-sonnet-4-20250514"``."""

    provider_name: str
    """Short provider name, e.g. ``"openai"``, ``"anthropic"``."""

    max_tokens: int = 4096
    """Maximum output token count."""


class Provider(ABC):
    """Abstract base for LLM providers.

    Subclasses must implement ``stream()`` and ``format_messages()``.
    The agent loop only interacts through these methods.
    """

    model: Model
    tools: ToolRegistry | None = None
    profile: ProviderProfile | None = None
    """Optional ProviderProfile with declarative metadata."""

    def __init__(self, model: Model) -> None:
        self.model = model
        self.tools = None
        self.profile = get_profile(model.provider_name)

    @abstractmethod
    def stream(
        self,
        messages: list[AgentMessage],
    ) -> AsyncIterator[StreamEvent]:
        """Stream LLM response tokens and tool calls.

        Args:
            messages: Conversation history in AgentMessage format.

        Yields:
            ``TextStreamEvent`` for each content token,
            ``ToolCallStreamEvent`` when a tool call is fully detected.

        Raises:
            ProviderError: On authentication, rate-limit, or API errors.
        """

    @abstractmethod
    def format_messages(self, messages: list[AgentMessage]) -> list[dict[str, Any]]:
        """Convert internal AgentMessages to provider-native format.

        Args:
            messages: Conversation history in AgentMessage format.

        Returns:
            A list of dicts in the provider's message format.
        """

    async def stream_with_retry(
        self,
        messages: list[AgentMessage],
    ) -> AsyncIterator[StreamEvent | RetryEvent]:
        """Stream with exponential backoff retry on transient errors.

        Retries on:
            - ``httpx.RequestError`` (network errors)
            - HTTP 429 / 500 / 502 / 503 (rate limit, server errors)

        Does not retry on:
            - HTTP 401 (auth error)
            - HTTP 400 (bad request)
            - Other client errors

        Yields:
            ``StreamEvent`` items from the provider stream, plus
            ``RetryEvent`` items when a retry/backoff occurs.
        """
        from agentsx.config import get_settings

        settings = get_settings()
        max_retries = settings.provider_retry_count
        base_delay = settings.provider_retry_base_delay
        max_delay = 10.0

        for attempt in range(max_retries + 1):
            try:
                async for event in self.stream(messages):
                    yield event
                return
            except ProviderError as exc:
                if exc.is_retryable and attempt < max_retries:
                    delay = self._calc_delay(attempt, base_delay, max_delay)
                    logger.warning(
                        "Provider %s error (attempt %d/%d), retrying in %.1fs: %s",
                        self.model.provider_name,
                        attempt + 1,
                        max_retries,
                        delay,
                        exc,
                    )
                    yield RetryEvent(
                        attempt=attempt + 1,
                        max_attempts=max_retries,
                        reason="provider error",
                        delay=delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
            except Exception as exc:
                if attempt < max_retries:
                    delay = self._calc_delay(attempt, base_delay, max_delay)
                    logger.warning(
                        "Provider %s unexpected error (attempt %d/%d), "
                        "retrying in %.1fs: %s",
                        self.model.provider_name,
                        attempt + 1,
                        max_retries,
                        delay,
                        exc,
                    )
                    yield RetryEvent(
                        attempt=attempt + 1,
                        max_attempts=max_retries,
                        reason="unexpected error",
                        delay=delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise RetryExhaustedError(
                    f"Provider {self.model.provider_name} "
                    f"retries exhausted after {max_retries} attempts",
                    exc,
                ) from exc

        raise RetryExhaustedError(
            f"Provider {self.model.provider_name} "
            f"retries exhausted after {max_retries} attempts",
            ProviderError("unknown"),
        )

    @staticmethod
    def _calc_delay(attempt: int, base: float, max_delay: float) -> float:
        """Calculate exponential backoff delay with jitter."""
        delay = min(base * (2**attempt), max_delay)
        jitter = delay * 0.5 * random.random()
        return float(delay + jitter)

    def resolve_api_key(self) -> str:
        """Resolve API key from constructor arg, env var, or settings."""
        return ""

    def resolve_api_base(self) -> str:
        """Resolve API base URL from constructor arg, env var, or settings."""
        return ""
