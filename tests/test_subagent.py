"""Tests for sub-agent runtime (``agentsx/agent/subagent.py``)
and orchestrator (``agentsx/orchestrator.py``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest

from agentsx.agent.subagent import (
    SubAgentConfig,
    SubAgentRuntime,
    _build_subagent_tools,
)
from agentsx.core.types import MessageRole
from agentsx.orchestrator import Orchestrator, SubAgentRecord


class TestSubAgentConfig:
    """SubAgentConfig dataclass construction."""

    def test_defaults(self) -> None:
        cfg = SubAgentConfig(model_name="gpt-4o")
        assert cfg.model_name == "gpt-4o"
        assert cfg.system_prompt == ""
        assert cfg.max_steps == 10
        assert cfg.allowed_tools is None
        assert cfg.timeout == 120
        assert cfg.max_spawn_depth == 2

    def test_custom(self) -> None:
        cfg = SubAgentConfig(
            model_name="claude-sonnet-4",
            system_prompt="Be concise.",
            max_steps=5,
            allowed_tools=["tool_file_read"],
            timeout=30,
            max_spawn_depth=3,
        )
        assert cfg.model_name == "claude-sonnet-4"
        assert cfg.system_prompt == "Be concise."
        assert cfg.max_steps == 5
        assert cfg.allowed_tools == ["tool_file_read"]
        assert cfg.timeout == 30
        assert cfg.max_spawn_depth == 3


class TestBuildSubagentTools:
    """Tool registry construction for sub-agents."""

    def test_default_tools_are_read_only(self) -> None:
        registry = _build_subagent_tools(None)
        tool_names = {t.name for t in registry.list_tools()}
        assert "tool_file_read" in tool_names
        assert "tool_file_glob" in tool_names
        assert "tool_file_grep" in tool_names
        assert "tool_web_fetch" in tool_names
        assert "tool_web_search" in tool_names
        assert "tool_file_write" not in tool_names
        assert "tool_file_edit" not in tool_names
        assert "tool_bash" not in tool_names

    def test_custom_tool_set(self) -> None:
        registry = _build_subagent_tools(["tool_file_read", "tool_bash"])
        tool_names = {t.name for t in registry.list_tools()}
        assert "tool_file_read" in tool_names
        assert "tool_bash" in tool_names
        assert "tool_file_grep" not in tool_names


class TestSubAgentRuntime:
    """SubAgentRuntime — isolated agent execution."""

    @pytest.fixture(autouse=True)
    def _mock_provider_factory(self) -> None:
        """Patch create_provider to avoid real provider imports."""
        import agentsx.agent.subagent as subagent_mod

        patcher = patch.object(subagent_mod, "create_provider")
        mock_factory = patcher.start()
        mock_provider = AsyncMock()
        mock_provider.model.id = "gpt-4o"
        mock_provider.model.provider_name = "openai"

        async def mock_stream(
            _messages: list[object],
        ) -> AsyncIterator[object]:
            from agentsx.core.types import TextStreamEvent

            yield TextStreamEvent(text="mock")

        mock_provider.stream = mock_stream
        mock_provider.format_messages.return_value = []
        mock_factory.return_value = mock_provider
        yield
        patcher.stop()

    async def test_run_returns_text(self) -> None:
        config = SubAgentConfig(
            model_name="gpt-4o",
            system_prompt="You are a test agent.",
        )
        runtime = SubAgentRuntime(config)
        result = await runtime.run("Hello")
        assert "mock" in result

    def test_id_is_unique(self) -> None:
        config = SubAgentConfig(model_name="gpt-4o")
        r1 = SubAgentRuntime(config)
        r2 = SubAgentRuntime(config)
        assert r1.id != r2.id

    def test_messages_initialized(self) -> None:
        config = SubAgentConfig(
            model_name="gpt-4o",
            system_prompt="System prompt here.",
        )
        runtime = SubAgentRuntime(config)
        assert len(runtime.messages) == 1
        assert runtime.messages[0].role == MessageRole.SYSTEM

    def test_messages_without_system_prompt(self) -> None:
        config = SubAgentConfig(model_name="gpt-4o")
        runtime = SubAgentRuntime(config)
        assert runtime.messages == []

    def test_repr(self) -> None:
        config = SubAgentConfig(model_name="gpt-4o")
        runtime = SubAgentRuntime(config)
        rep = repr(runtime)
        assert runtime.id in rep
        assert "gpt-4o" in rep

    def test_spawn_depth_property(self) -> None:
        config = SubAgentConfig(model_name="gpt-4o")
        runtime = SubAgentRuntime(config, spawn_depth=1)
        assert runtime.spawn_depth == 1


class TestOrchestrator:
    """Orchestrator — sub-agent lifecycle management."""

    def test_max_active_default(self) -> None:
        o = Orchestrator(max_active=3)
        assert o.max_active == 3

    def test_max_spawn_depth_default(self) -> None:
        o = Orchestrator()
        assert o.max_spawn_depth == 2

    def test_list_active_empty(self) -> None:
        o = Orchestrator()
        assert o.list_active() == []

    async def test_spawn_runtime_error(self) -> None:
        o = Orchestrator(max_active=1)
        config = SubAgentConfig(model_name="gpt-4o", timeout=3600)

        import asyncio

        first_started = asyncio.Event()

        class _HangingRuntime:
            """A mock sub-agent that never completes."""

            def __init__(self, _cfg: SubAgentConfig) -> None:
                self.id = "hanging-agent"

            async def run(self, _prompt: str) -> str:
                first_started.set()
                await asyncio.sleep(3600)
                return "never"

        with patch("agentsx.orchestrator.SubAgentRuntime", _HangingRuntime):
            first_task = asyncio.create_task(o.spawn(config, "task1"))
            await first_started.wait()

            with pytest.raises(RuntimeError, match="Maximum active"):
                await o.spawn(config, "task2")

            first_task.cancel()
            try:
                await first_task
            except (asyncio.CancelledError, TimeoutError):
                pass

    @patch("agentsx.agent.subagent.create_provider")
    def test_sub_agent_record_defaults(
        self,
        mock_factory: object,
    ) -> None:
        mock_provider = AsyncMock()
        mock_provider.model.id = "gpt-4o"

        async def mock_stream(
            _messages: list[object],
        ) -> AsyncIterator[object]:
            from agentsx.core.types import TextStreamEvent

            yield TextStreamEvent(text="mock")

        mock_provider.stream = mock_stream
        mock_provider.format_messages.return_value = []
        mock_factory.return_value = mock_provider  # type: ignore[union-attr]

        config = SubAgentConfig(model_name="gpt-4o")
        runtime = SubAgentRuntime(config)
        import time

        record = SubAgentRecord(
            runtime=runtime,
            spawned_at=time.time(),
            prompt="test prompt",
            depth=0,
        )
        assert record.result is None
        assert record.error is None

    async def test_spawn_timeout(self) -> None:
        o = Orchestrator(max_active=5)
        config = SubAgentConfig(model_name="gpt-4o", timeout=1)

        with patch(
            "agentsx.orchestrator.SubAgentRuntime",
        ) as mock_runtime_cls:
            mock_runtime = AsyncMock()
            mock_runtime.id = "slow-agent"

            import asyncio

            async def never_ending(_prompt: str) -> str:
                await asyncio.sleep(3600)
                return "never"

            mock_runtime.run = never_ending
            mock_runtime_cls.return_value = mock_runtime

            with pytest.raises((TimeoutError, asyncio.TimeoutError)):
                await o.spawn(config, "slow task")
