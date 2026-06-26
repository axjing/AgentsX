"""Tests for provider abstraction and implementations."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from agentsx.core.errors import ProviderError
from agentsx.core.types import AgentMessage, StreamEvent
from agentsx.provider import (
    _PROVIDER_REGISTRY,
    Model,
    Provider,
    create_provider,
    register_provider,
)


class TestModel:
    """Model dataclass construction."""

    def test_basic(self) -> None:
        m = Model(id="gpt-4o", provider_name="openai")
        assert m.id == "gpt-4o"
        assert m.provider_name == "openai"
        assert m.max_tokens == 4096

    def test_custom_max_tokens(self) -> None:
        m = Model(id="claude-sonnet-4", provider_name="anthropic", max_tokens=8192)
        assert m.max_tokens == 8192


class TestProviderABC:
    """Provider ABC cannot be instantiated directly."""

    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            Provider(model=Model(id="x", provider_name="x"))  # type: ignore[abstract]


class TestRegistry:
    """Provider registration and factory."""

    def setup_method(self) -> None:
        _PROVIDER_REGISTRY.clear()

    def _register_dummy(self) -> None:
        class DummyProvider(Provider):
            def __init__(self, model: Model) -> None:
                self.model = model

            async def stream(
                self,
                messages: list[AgentMessage],
            ) -> AsyncIterator[StreamEvent]:
                for m in messages:
                    from agentsx.core.types import TextStreamEvent

                    yield TextStreamEvent(text=str(m.content))

            def format_messages(
                self,
                messages: list[AgentMessage],
            ) -> list[dict[str, Any]]:
                return [{"role": m.role.value, "content": m.content} for m in messages]

        register_provider("dummy", DummyProvider)

    def test_register_and_create(self) -> None:
        self._register_dummy()
        prov = create_provider("dummy-model")
        assert prov.model.id == "dummy-model"
        assert prov.model.provider_name == "dummy"

    def test_unknown_model_raises(self) -> None:
        self._register_dummy()
        with pytest.raises(ProviderError, match="No provider registered"):
            create_provider("unknown-model")

    def test_empty_registry_raises(self) -> None:
        _PROVIDER_REGISTRY.clear()
        with pytest.raises(ProviderError, match="No provider registered"):
            create_provider("anything")


class TestOpenAIParseChunk:
    """OpenAI SSE chunk parsing logic."""

    def test_content_chunk(self) -> None:
        from agentsx.provider.openai import _parse_sse_chunk

        result = _parse_sse_chunk(
            '{"choices":[{"delta":{"content":"Hello"}}]}',
        )
        assert result is not None
        assert result["text"] == "Hello"

    def test_no_choices(self) -> None:
        from agentsx.provider.openai import _parse_sse_chunk

        assert _parse_sse_chunk("{}") is None

    def test_invalid_json(self) -> None:
        from agentsx.provider.openai import _parse_sse_chunk

        assert _parse_sse_chunk("not-json") is None

    def test_empty_delta(self) -> None:
        from agentsx.provider.openai import _parse_sse_chunk

        result = _parse_sse_chunk('{"choices":[{"delta":{}}]}')
        assert result is not None
        assert "text" not in result

    def test_tool_call_chunk(self) -> None:
        from agentsx.provider.openai import _parse_sse_chunk

        result = _parse_sse_chunk(
            '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1",'
            '"function":{"name":"read","arguments":""}}]},'
            '"finish_reason":"tool_calls"}]}',
        )
        assert result is not None
        assert result.get("tool_calls") is not None


class TestAnthropicParseChunk:
    """Anthropic SSE event parsing relies on the provider's stream method."""

    def test_placeholder(self) -> None:
        pass
