"""Provider profile — declarative provider metadata.

Inspired by Hermes-Agent's ProviderProfile pattern: a single dataclass
captures all provider variability (auth, endpoints, capabilities, quirks)
instead of scattering it across ad-hoc mappings and conditional branches.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProviderProfile:
    """Declarative metadata for an LLM provider.

    Usage::

        openai_profile = ProviderProfile(
            name="openai",
            display_name="OpenAI",
            base_url="https://api.openai.com/v1",
            env_api_key="AGENTSX_OPENAI_API_KEY",
            env_api_base="AGENTSX_OPENAI_API_BASE",
            default_model="gpt-4o",
            supports_vision=True,
        )
    """

    # ── Identity ─────────────────────────────────────────────
    name: str
    """Short unique identifier, e.g. ``"openai"``, ``"anthropic"``."""

    display_name: str = ""
    """Human-readable label, e.g. ``"OpenAI"``, ``"Anthropic"``."""

    # ── Endpoint ─────────────────────────────────────────────
    base_url: str = ""
    """Default API base URL."""

    api_format: str = "openai"
    """API message format: ``"openai"`` or ``"anthropic"``."""

    # ── Auth ─────────────────────────────────────────────────
    env_api_key: str = ""
    """Environment variable name for the API key."""

    env_api_base: str = ""
    """Environment variable name for the API base URL override."""

    # ── Model defaults ───────────────────────────────────────
    default_model: str = ""
    """Default model identifier for this provider."""

    max_tokens: int = 4096
    """Default max output tokens."""

    context_window: int = 0
    """Maximum context window size (0 = unknown)."""

    # ── Capabilities ─────────────────────────────────────────
    supports_tools: bool = True
    """Provider supports tool/function calling."""

    supports_streaming: bool = True
    """Provider supports streaming responses."""

    supports_vision: bool = False
    """Provider supports image inputs."""

    supports_audio: bool = False
    """Provider supports audio inputs."""

    # ── API behavior ─────────────────────────────────────────
    requires_tools_on_first_turn: bool = False
    """Some providers (e.g. Anthropic) require tools on the first turn."""

    anthropic_version: str = ""
    """Anthropic API version header value (only for Anthropic profiles)."""

    rate_limit_rpm: int = 0
    """Requests per minute rate limit (0 = unknown / no limit)."""

    extra_headers: dict[str, str] = field(default_factory=dict)
    """Extra HTTP headers to include in every request."""

    # ── Aliases ──────────────────────────────────────────────
    model_prefix: str = ""
    """Model name prefix for auto-matching, e.g. ``"gpt-"``, ``"claude-"``."""

    model_aliases: dict[str, str] = field(default_factory=dict)
    """Known model name → provider mapping overrides."""


# ── Built-in profiles ─────────────────────────────────────────

OPENAI_PROFILE = ProviderProfile(
    name="openai",
    display_name="OpenAI",
    base_url="https://api.openai.com/v1",
    api_format="openai",
    env_api_key="AGENTSX_OPENAI_API_KEY",
    env_api_base="AGENTSX_OPENAI_API_BASE",
    default_model="gpt-4o",
    context_window=128_000,
    supports_vision=True,
    model_prefix="gpt-",
    model_aliases={
        "o1": "openai",
        "o3-mini": "openai",
    },
)

ANTHROPIC_PROFILE = ProviderProfile(
    name="anthropic",
    display_name="Anthropic",
    base_url="https://api.anthropic.com/v1",
    api_format="anthropic",
    env_api_key="AGENTSX_ANTHROPIC_API_KEY",
    env_api_base="AGENTSX_ANTHROPIC_API_BASE",
    default_model="claude-sonnet-4-20250514",
    context_window=200_000,
    supports_vision=True,
    anthropic_version="2023-06-01",
    requires_tools_on_first_turn=True,
    model_prefix="claude-",
    extra_headers={"anthropic-version": "2023-06-01"},
    model_aliases={
        "claude-sonnet-4-20250514": "anthropic",
        "claude-opus-4-20250414": "anthropic",
        "claude-haiku-4-20250414": "anthropic",
    },
)

GEMINI_PROFILE = ProviderProfile(
    name="gemini",
    display_name="Google Gemini",
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    api_format="openai",
    env_api_key="AGENTSX_GEMINI_API_KEY",
    default_model="gemini-2.0-flash",
    supports_vision=True,
    model_prefix="gemini-",
)

DEEPSEEK_PROFILE = ProviderProfile(
    name="deepseek",
    display_name="DeepSeek",
    base_url="https://api.deepseek.com/v1",
    api_format="openai",
    env_api_key="AGENTSX_DEEPSEEK_API_KEY",
    default_model="deepseek-chat",
    max_tokens=8192,
    model_prefix="deepseek-",
)

GROQ_PROFILE = ProviderProfile(
    name="groq",
    display_name="Groq",
    base_url="https://api.groq.com/openai/v1",
    api_format="openai",
    env_api_key="AGENTSX_GROQ_API_KEY",
    default_model="llama-3.3-70b-versatile",
    model_prefix="llama-",
)

OPENROUTER_PROFILE = ProviderProfile(
    name="openrouter",
    display_name="OpenRouter",
    base_url="https://openrouter.ai/api/v1",
    api_format="openai",
    env_api_key="AGENTSX_OPENROUTER_API_KEY",
    default_model="",
    model_prefix="",
    extra_headers={
        "HTTP-Referer": "https://agentsx.local",
        "X-Title": "AgentsX",
    },
)

OLLAMA_PROFILE = ProviderProfile(
    name="ollama",
    display_name="Ollama",
    base_url="http://localhost:11434/v1",
    api_format="openai",
    env_api_key="",
    default_model="llama3",
    model_prefix="",
)

VLLM_PROFILE = ProviderProfile(
    name="vllm",
    display_name="vLLM",
    base_url="http://localhost:8000/v1",
    api_format="openai",
    env_api_key="AGENTSX_VLLM_API_KEY",
    env_api_base="AGENTSX_VLLM_API_BASE",
    default_model="",
    model_prefix="",
)

SGLANG_PROFILE = ProviderProfile(
    name="sglang",
    display_name="SGLang",
    base_url="http://localhost:30000/v1",
    api_format="openai",
    env_api_key="AGENTSX_SGLANG_API_KEY",
    env_api_base="AGENTSX_SGLANG_API_BASE",
    default_model="",
    model_prefix="",
)

# Registered profiles lookup
_BUILTIN_PROFILES: dict[str, ProviderProfile] = {
    "openai": OPENAI_PROFILE,
    "anthropic": ANTHROPIC_PROFILE,
    "gemini": GEMINI_PROFILE,
    "deepseek": DEEPSEEK_PROFILE,
    "groq": GROQ_PROFILE,
    "openrouter": OPENROUTER_PROFILE,
    "ollama": OLLAMA_PROFILE,
    "vllm": VLLM_PROFILE,
    "sglang": SGLANG_PROFILE,
}


def get_profile(name: str) -> ProviderProfile | None:
    """Look up a built-in profile by name."""
    return _BUILTIN_PROFILES.get(name)


def register_profile(name: str, profile: ProviderProfile) -> None:
    """Register a custom profile."""
    _BUILTIN_PROFILES[name] = profile


def resolve_provider_name(model_name: str) -> str | None:
    """Resolve a model name to a provider name.

    Priority:
    1. Slash notation: ``"gemini/gemini-2.0-flash"`` → ``"gemini"``
    2. Explicit model alias lookup across all profiles
    3. Prefix matching against profile ``model_prefix``
    """
    if "/" in model_name:
        return model_name.split("/")[0]

    for pname, profile in _BUILTIN_PROFILES.items():
        if model_name in profile.model_aliases:
            return pname

    for pname, profile in _BUILTIN_PROFILES.items():
        prefix = profile.model_prefix
        if prefix and model_name.startswith(prefix):
            return pname

    return None
