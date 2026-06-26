"""Configuration for AgentsX.

All settings are read from ``AGENTSX_*`` environment variables.
Uses Pydantic Settings for validation and type coercion.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentsXSettings(BaseSettings):
    """Global AgentsX configuration.

    Usage::

        from agentsx.config import settings

        settings.model_name   # "gpt-4o"
        settings.max_steps    # 25
    """

    model_config = SettingsConfigDict(
        env_prefix="AGENTSX_",
        env_file=".env",
        extra="ignore",
    )

    # ── Model ──
    model_name: str = "gpt-4o"
    """Default LLM model identifier."""

    api_key: str = "sk-5PQREuaqS3g8ybOdfVC5xJE223OMVKDBWbg1nx2pT6LtxWNc"
    """Default API key for the LLM provider."""

    api_base: str = "https://lonlie.plus7.plus/v1"
    """Optional custom API base URL."""

    # ── Agent ──
    max_steps: int = 25
    """Maximum tool-calling iterations per conversation."""

    system_prompt: str = "You are a helpful AI assistant."
    """Default system prompt."""

    # ── Session ──
    session_dir: str = ""
    """Session storage directory. Empty = ``~/.agentsx/sessions/``."""

    # ── Security ──
    policy_default: str = "prompt"
    """Default security policy: ``"allow"``, ``"prompt"``, or ``"forbidden"``."""

    # ── Provider: OpenAI ──
    openai_api_key: str = ""
    """OpenAI API key. Reads from ``AGENTSX_OPENAI_API_KEY``."""

    openai_api_base: str = ""
    """OpenAI API base URL. Reads from ``AGENTSX_OPENAI_API_BASE``."""

    # ── Provider: Anthropic ──
    anthropic_api_key: str = ""
    """Anthropic API key. Reads from ``AGENTSX_ANTHROPIC_API_KEY``."""

    anthropic_api_base: str = ""
    """Anthropic API base URL. Reads from ``AGENTSX_ANTHROPIC_API_BASE``."""

    # ── Tools ──
    tool_timeout: int = 30
    """Default tool execution timeout in seconds."""

    # ── High Availability ──
    provider_retry_count: int = 3
    """Number of retries for provider API calls."""

    provider_retry_base_delay: float = 1.0
    """Base delay for exponential backoff (seconds)."""

    loop_timeout: float = 0
    """Wall-clock timeout for the entire agent loop (0 = disabled)."""


settings = AgentsXSettings()
"""Module-level singleton. Import and use directly."""


def get_settings() -> AgentsXSettings:
    """Return the global settings singleton.

    Provider modules should call this at call-time (not import-time)
    to allow settings to be reconfigured after import.
    """
    return settings
