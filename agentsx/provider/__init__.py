"""LLM Provider abstraction layer.

Each provider implements the ``Provider`` ABC with ``stream()`` and
``format_messages()``. The ``create_provider()`` factory selects the
right provider by model name.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import random
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from agentsx.config import get_settings
from agentsx.core.errors import ProviderError, RetryExhaustedError
from agentsx.core.types import AgentMessage, StreamEvent

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
    tools: Any = None
    """Optional ToolRegistry. Set before calling ``stream()`` to expose
    tools to the LLM."""

    def __init__(self, model: Model) -> None:
        self.model = model
        self.tools = None

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
    ) -> AsyncIterator[StreamEvent]:
        """Stream with exponential backoff retry on transient errors.

        Retries on:
            - ``httpx.RequestError`` (network errors)
            - HTTP 429 / 500 / 502 / 503 (rate limit, server errors)

        Does not retry on:
            - HTTP 401 (auth error)
            - HTTP 400 (bad request)
            - Other client errors
        """
        settings = get_settings()
        max_retries = settings.provider_retry_count
        base_delay = settings.provider_retry_base_delay
        max_delay = 10.0

        for attempt in range(max_retries + 1):
            try:
                async for event in self.stream(messages):
                    yield event
                return  # Success
            except ProviderError as exc:
                if self._is_retryable(exc) and attempt < max_retries:
                    delay = self._calc_delay(attempt, base_delay, max_delay)
                    logger.warning(
                        "Provider %s error (attempt %d/%d), retrying in %.1fs: %s",
                        self.model.provider_name,
                        attempt + 1,
                        max_retries,
                        delay,
                        exc,
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
    def _is_retryable(error: ProviderError) -> bool:
        """Check if a ProviderError is retryable based on HTTP status."""
        msg = str(error).lower()
        return any(
            token in msg for token in ["429", "500", "502", "503", "504", "rate limit"]
        )

    @staticmethod
    def _calc_delay(attempt: int, base: float, max_delay: float) -> float:
        """Calculate exponential backoff delay with jitter."""
        delay = min(base * (2**attempt), max_delay)
        jitter = delay * 0.5 * random.random()
        return float(delay + jitter)


# ── Provider Registry ──────────────────────────────────────────────────

_PROVIDER_REGISTRY: dict[str, type[Provider]] = {}


def register_provider(name: str, provider_cls: type[Provider]) -> None:
    """Register a provider class for use by ``create_provider()``."""
    _PROVIDER_REGISTRY[name] = provider_cls


def create_provider(
    model_name: str,
    api_key: str | None = None,
    api_base: str | None = None,
    **kwargs: object,
) -> Provider:
    """Factory: create a Provider instance from a model name.

    Model name resolution (in order of priority):
        1. Slash notation: ``"gemini/gemini-2.0-flash"`` -> ``gemini``
        2. Explicit mapping: ``"deepseek-chat"`` -> ``deepseek``
        3. Prefix matching: ``"gpt-4o"`` -> ``openai``

    Args:
        model_name: Model identifier (e.g. ``"gpt-4o"`` or ``"gemini/gemini-2.0-flash"``).
        api_key: API key for the provider.
        api_base: Optional custom API base URL.
        **kwargs: Additional provider-specific arguments.

    Returns:
        A configured Provider instance.

    Raises:
        ProviderError: If no provider is registered for the model.
    """
    # Load all provider modules
    for _mod in (
        "agentsx.provider.openai",
        "agentsx.provider.anthropic",
        "agentsx.provider.generic",
    ):
        try:
            importlib.import_module(_mod)
        except ImportError:
            pass

    # Extract clean model ID (remove provider prefix if slash notation)
    if "/" in model_name:
        provider_hint = model_name.split("/")[0]
        clean_model = model_name.split("/", 1)[1]
    else:
        provider_hint = None
        clean_model = model_name

    init_kwargs: dict[str, object] = {}
    if api_key is not None:
        init_kwargs["api_key"] = api_key
    if api_base is not None:
        init_kwargs["api_base"] = api_base
    init_kwargs.update(kwargs)

    # Try explicit provider hint first
    if provider_hint and provider_hint in _PROVIDER_REGISTRY:
        resolved_kwargs = _resolve_provider_kwargs(provider_hint, init_kwargs)
        return _PROVIDER_REGISTRY[provider_hint](
            model=Model(id=clean_model, provider_name=provider_hint),
            **resolved_kwargs,
        )

    # Try explicit mapping
    resolved = _resolve_provider_name(model_name)
    if resolved and resolved in _PROVIDER_REGISTRY:
        resolved_kwargs = _resolve_provider_kwargs(resolved, init_kwargs)
        return _PROVIDER_REGISTRY[resolved](
            model=Model(id=clean_model, provider_name=resolved),
            **resolved_kwargs,
        )

    # Try prefix matching
    for name, cls in _PROVIDER_REGISTRY.items():
        prefix = _provider_prefix(name)
        if prefix and model_name.startswith(prefix):
            resolved_kwargs = _resolve_provider_kwargs(name, init_kwargs)
            return cls(
                model=Model(id=clean_model, provider_name=name),
                **resolved_kwargs,
            )

    msg = f"No provider registered for model: {model_name}"
    raise ProviderError(msg)


def _resolve_provider_kwargs(
    provider_name: str,
    init_kwargs: dict[str, object],
) -> dict[str, object]:
    """Apply generic api_key/api_base fallback for a provider.

    When no provider-specific key is configured, the generic
    `api_key` and `api_base` settings are used as fallback.
    """
    settings = get_settings()
    resolved = dict(init_kwargs)
    if not resolved.get("api_key"):
        key_attr = f"{provider_name}_api_key"
        generic_key = getattr(settings, key_attr, "") or settings.api_key
        resolved["api_key"] = generic_key
    if not resolved.get("api_base"):
        base_attr = f"{provider_name}_api_base"
        generic_base = getattr(settings, base_attr, "") or settings.api_base
        resolved["api_base"] = generic_base
    return resolved


def _provider_prefix(provider_name: str) -> str:
    """Map provider names to model name prefixes."""
    mapping = {
        "openai": "gpt-",
        "anthropic": "claude-",
        "gemini": "gemini-",
        "deepseek": "deepseek-",
        "groq": "llama-|mixtral-",
        "openrouter": "",
        "ollama": "",
        "vllm": "",
        "sglang": "",
        "custom": "",
    }
    return mapping.get(provider_name, provider_name)


# Model name to provider mapping (explicit overrides)
_MODEL_TO_PROVIDER: dict[str, str] = {
    # Google Gemini
    "gemini-2.0-flash": "gemini",
    "gemini-2.0-flash-lite": "gemini",
    "gemini-2.5-pro": "gemini",
    "gemini-2.5-flash": "gemini",
    "gemini-1.5-pro": "gemini",
    "gemini-1.5-flash": "gemini",
    # DeepSeek
    "deepseek-chat": "deepseek",
    "deepseek-coder": "deepseek",
    "deepseek-reasoner": "deepseek",
    # Groq
    "llama-3.3-70b-versatile": "groq",
    "llama-3.1-8b-instant": "groq",
    "mixtral-8x7b-32768": "groq",
    # Common model aliases
    "gpt-4o": "openai",
    "gpt-4o-mini": "openai",
    "o1": "openai",
    "o3-mini": "openai",
    "claude-sonnet-4-20250514": "anthropic",
    "claude-opus-4-20250414": "anthropic",
    "claude-haiku-4-20250414": "anthropic",
    # vLLM common model IDs
    "meta-llama/Llama-3.1-70B-Instruct": "vllm",
    "meta-llama/Llama-3.1-8B-Instruct": "vllm",
    "Qwen/Qwen2.5-72B-Instruct": "vllm",
    "Qwen/Qwen2.5-Coder-32B-Instruct": "vllm",
    "mistralai/Mixtral-8x7B-Instruct-v0.1": "vllm",
    # SGLang common model IDs
    "meta-llama/Llama-3.1-70B-Instruct": "sglang",
    "meta-llama/Llama-3.1-8B-Instruct": "sglang",
    "Qwen/Qwen2.5-72B-Instruct": "sglang",
    "Qwen/Qwen2.5-Coder-32B-Instruct": "sglang",
}


def _resolve_provider_name(model_name: str) -> str | None:
    """Resolve a model name to a provider name.

    Supports:
    - Explicit slash notation: "gemini/gemini-2.0-flash" -> "gemini"
    - Explicit mapping: "deepseek-chat" -> "deepseek"
    - Prefix matching: "gpt-4o" -> "openai"
    """
    # Slash notation takes highest priority
    if "/" in model_name:
        return model_name.split("/")[0]

    # Explicit mapping
    if model_name in _MODEL_TO_PROVIDER:
        return _MODEL_TO_PROVIDER[model_name]

    # Prefix matching
    _prefixes = {
        "openai": "gpt-",
        "anthropic": "claude-",
        "gemini": "gemini-",
        "deepseek": "deepseek-",
        "groq": "llama-",
        "openrouter": "",
        "ollama": "",
        "vllm": "",
        "sglang": "",
        "custom": "",
    }
    for name, prefix in _prefixes.items():
        if prefix and model_name.startswith(prefix):
            return name

    return None
