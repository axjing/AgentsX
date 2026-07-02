"""Configuration for AgentsX.

All settings are read from ``AGENTSX_*`` environment variables.
Uses Pydantic Settings for validation and type coercion.
"""

from pydantic import Field
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

    api_key: str = ""
    """Default API key for the LLM provider. Must be set via AGENTSX_API_KEY."""

    api_base: str = ""
    """Optional custom API base URL. Must be set via AGENTSX_API_BASE."""

    # ── Agent ──
    max_steps: int = Field(default=25, ge=1, le=200)
    """Maximum tool-calling iterations per conversation."""

    system_prompt: str = "You are a helpful AI assistant."
    """Default system prompt."""

    # ── Session ──
    session_dir: str = ""
    """Session storage directory. Empty = ``~/.agentsx/sessions/``."""

    # ── Discovery ──
    discovery_dir: str = ""
    """Base directory for command/skill discovery. Empty = ``~/.agentsx/``."""

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

    # ── Provider: Gemini ──
    gemini_api_key: str = ""
    """Gemini API key. Reads from ``AGENTSX_GEMINI_API_KEY``."""

    # ── Provider: DeepSeek ──
    deepseek_api_key: str = ""
    """DeepSeek API key. Reads from ``AGENTSX_DEEPSEEK_API_KEY``."""

    # ── Provider: Groq ──
    groq_api_key: str = ""
    """Groq API key. Reads from ``AGENTSX_GROQ_API_KEY``."""

    # ── Provider: OpenRouter ──
    openrouter_api_key: str = ""
    """OpenRouter API key. Reads from ``AGENTSX_OPENROUTER_API_KEY``."""

    # ── Provider: vLLM ──
    vllm_api_key: str = ""
    """vLLM API key. Reads from ``AGENTSX_VLLM_API_KEY``."""

    vllm_api_base: str = ""
    """vLLM API base URL. Reads from ``AGENTSX_VLLM_API_BASE``."""

    # ── Provider: SGLang ──
    sglang_api_key: str = ""
    """SGLang API key. Reads from ``AGENTSX_SGLANG_API_KEY``."""

    sglang_api_base: str = ""
    """SGLang API base URL. Reads from ``AGENTSX_SGLANG_API_BASE``."""

    # ── Tools ──
    tool_timeout: int = Field(default=30, ge=1, le=600)
    """Default tool execution timeout in seconds."""

    # ── High Availability ──
    provider_retry_count: int = Field(default=3, ge=0, le=10)
    """Number of retries for provider API calls."""

    provider_retry_base_delay: float = Field(default=1.0, gt=0, le=30.0)
    """Base delay for exponential backoff (seconds)."""

    loop_timeout: float = Field(default=0, ge=0)
    """Wall-clock timeout for the entire agent loop (0 = disabled)."""

    max_tool_output: int = Field(default=50000, ge=0, le=1_000_000)
    """Maximum characters returned by a single tool call (0 = no limit)."""

    # ── Web Tools ──
    web_search_url: str = "https://html.duckduckgo.com/html/"
    """Web search engine URL. Reads from ``AGENTSX_WEB_SEARCH_URL``."""

    web_user_agent: str = (
        "Mozilla/5.0 (compatible; AgentsX/0.1.0; +https://github.com/agentsx)"
    )
    """User-Agent header for HTTP requests. Reads from ``AGENTSX_WEB_USER_AGENT``."""


settings = AgentsXSettings()
"""Module-level singleton. Import and use directly."""


def get_settings() -> AgentsXSettings:
    """Return the global settings singleton.

    Provider modules should call this at call-time (not import-time)
    to allow settings to be reconfigured after import.
    """
    return settings
