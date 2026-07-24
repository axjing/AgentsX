"""Tests for the provider catalog loader and resolver."""

from agentsx.provider.catalog import (
    _entries_from_raw,
    _merge_catalogs,
    resolve_model,
)


class TestEntriesFromRaw:
    """Test raw TOML → ProviderEntry conversion."""

    def test_minimal_entry(self):
        raw = [{"name": "test", "base_url": "http://localhost"}]
        entries = _entries_from_raw(raw)
        assert "test" in entries
        assert entries["test"].name == "test"
        assert entries["test"].base_url == "http://localhost"
        assert entries["test"].api_format == "openai"  # default
        assert entries["test"].models == {}

    def test_full_entry(self):
        raw = [
            {
                "name": "openai",
                "display_name": "OpenAI",
                "base_url": "https://api.openai.com/v1",
                "api_format": "openai",
                "env_api_key": "OPENAI_API_KEY",
                "default_model": "gpt-4o",
                "context_window": 128_000,
                "supports_vision": True,
                "model_prefix": "gpt-",
                "extra_headers": {"Custom": "value"},
                "models": {
                    "gpt-4o": {"context_window": 128_000},
                    "gpt-4o-mini": {"context_window": 128_000},
                },
            }
        ]
        entries = _entries_from_raw(raw)
        entry = entries["openai"]
        assert entry.display_name == "OpenAI"
        assert entry.default_model == "gpt-4o"
        assert entry.context_window == 128_000
        assert entry.supports_vision is True
        assert entry.model_prefix == "gpt-"
        assert "gpt-4o" in entry.models
        assert entry.models["gpt-4o"].context_window == 128_000
        assert entry.extra_headers == {"Custom": "value"}


class TestMergeCatalogs:
    """Test builtin + user catalog merging."""

    def test_user_overrides_builtin(self):
        builtin = _entries_from_raw(
            [
                {
                    "name": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "default_model": "gpt-4o",
                }
            ]
        )
        user = _entries_from_raw([{"name": "openai", "default_model": "gpt-4o-mini"}])
        merged = _merge_catalogs(builtin, user)
        assert merged["openai"].default_model == "gpt-4o-mini"
        assert merged["openai"].base_url == "https://api.openai.com/v1"  # preserved

    def test_user_adds_new_provider(self):
        builtin = _entries_from_raw(
            [{"name": "openai", "base_url": "https://api.openai.com/v1"}]
        )
        user = _entries_from_raw(
            [{"name": "my-llm", "base_url": "http://localhost:8000/v1"}]
        )
        merged = _merge_catalogs(builtin, user)
        assert "openai" in merged
        assert "my-llm" in merged

    def test_model_merge(self):
        builtin = _entries_from_raw(
            [
                {
                    "name": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "models": {"gpt-4o": {"context_window": 128_000}},
                }
            ]
        )
        user = _entries_from_raw(
            [
                {
                    "name": "openai",
                    "models": {"gpt-5": {"context_window": 200_000}},
                }
            ]
        )
        merged = _merge_catalogs(builtin, user)
        assert "gpt-4o" in merged["openai"].models
        assert "gpt-5" in merged["openai"].models


class TestResolveModel:
    """Test model name → (ProviderEntry, clean_model) resolution."""

    def test_slash_notation(self):
        catalog = _entries_from_raw(
            [
                {
                    "name": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "models": {"gpt-4o": {}},
                },
                {
                    "name": "anthropic",
                    "base_url": "https://api.anthropic.com/v1",
                    "models": {"claude-sonnet": {}},
                },
            ]
        )
        result = resolve_model("openai/gpt-4o", catalog)
        assert result is not None
        entry, model = result
        assert entry.name == "openai"
        assert model == "gpt-4o"

    def test_exact_model_lookup(self):
        catalog = _entries_from_raw(
            [
                {
                    "name": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "models": {"gpt-4o": {}},
                },
            ]
        )
        result = resolve_model("gpt-4o", catalog)
        assert result is not None
        entry, model = result
        assert entry.name == "openai"
        assert model == "gpt-4o"

    def test_prefix_matching(self):
        catalog = _entries_from_raw(
            [
                {
                    "name": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "model_prefix": "gpt-",
                    "models": {},
                },
            ]
        )
        result = resolve_model("gpt-4o", catalog)
        assert result is not None
        entry, model = result
        assert entry.name == "openai"
        assert model == "gpt-4o"

    def test_qwen_model(self):
        catalog = _entries_from_raw(
            [
                {
                    "name": "qwen",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "model_prefix": "qwen",
                    "models": {"qwen3.6-plus": {}},
                },
            ]
        )
        result = resolve_model("qwen3.6-plus", catalog)
        assert result is not None
        entry, model = result
        assert entry.name == "qwen"
        assert model == "qwen3.6-plus"

    def test_not_found(self):
        catalog = _entries_from_raw(
            [
                {
                    "name": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "models": {"gpt-4o": {}},
                },
            ]
        )
        result = resolve_model("unknown-model", catalog)
        assert result is None

    def test_provider_hint_unknown_provider(self):
        """Unknown provider hint returns None."""
        catalog = _entries_from_raw(
            [
                {"name": "openai", "base_url": "https://api.openai.com/v1"},
            ]
        )
        result = resolve_model("fake-provider/some-model", catalog)
        assert result is None
