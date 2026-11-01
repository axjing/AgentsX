"""Tests for sub-agent runtime (``agentsx/agent/subagent.py``)
and orchestrator (``agentsx/orchestrator.py``).
"""

import asyncio
import time
from collections.abc import AsyncIterator, Generator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentsx.agent.subagent import (
    SubAgentConfig,
    SubAgentRole,
    SubAgentRuntime,
    _build_subagent_tools,
)
from agentsx.orchestrator import Orchestrator, SubAgentRecord
from agentsx.protocol.events import StreamEvent, TextStreamEvent
from agentsx.protocol.messages import AgentMessage, Decision, MessageRole
from agentsx.provider import Model, Provider
from agentsx.tools.builtin.orchestration.subagent import spawn_agent


class TestSubAgentConfig:
    """SubAgentConfig dataclass construction."""

    def test_defaults(self) -> None:
        cfg = SubAgentConfig(model_name="gpt-4o")
        assert cfg.model_name == "gpt-4o"
        assert cfg.system_prompt == ""
        assert cfg.workdir == ""
        assert cfg.max_steps == 10
        assert cfg.allowed_tools is None
        assert cfg.timeout == 120
        assert cfg.max_spawn_depth == 2

    def test_custom(self) -> None:
        cfg = SubAgentConfig(
            model_name="claude-sonnet-4",
            system_prompt="Be concise.",
            workdir="/tmp/sandbox",
            max_steps=5,
            allowed_tools=["tool_file_read"],
            timeout=30,
            max_spawn_depth=3,
        )
        assert cfg.model_name == "claude-sonnet-4"
        assert cfg.system_prompt == "Be concise."
        assert cfg.workdir == "/tmp/sandbox"
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
    def _mock_provider_factory(self) -> Generator[None, None, None]:
        """Patch create_provider to avoid real provider imports."""
        import agentsx.agent.subagent as subagent_mod

        patcher = patch.object(subagent_mod, "create_provider")
        mock_factory = patcher.start()

        class _MockProvider(Provider):
            def __init__(self) -> None:
                self.model = Model(
                    id="gpt-4o",
                    provider_name="openai",
                    max_tokens=4096,
                )
                self.tools = None

            async def stream(
                self,
                messages: list[AgentMessage],
            ) -> AsyncIterator[StreamEvent]:
                yield TextStreamEvent(text="mock")

            def format_messages(
                self,
                messages: list[AgentMessage],
            ) -> list[dict[str, object]]:
                return []

        mock_provider = _MockProvider()
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

    def test_workdir_confinement_policy(self, tmp_path: Path) -> None:
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        allowed_file = sandbox / "allowed.txt"
        allowed_file.write_text("hello", encoding="utf-8")

        outside_file = tmp_path / "outside.txt"
        outside_file.write_text("secret", encoding="utf-8")

        config = SubAgentConfig(model_name="gpt-4o", workdir=str(sandbox))
        runtime = SubAgentRuntime(config)

        assert runtime.workdir == str(sandbox)
        # Inside sandbox should be allowed
        assert (
            runtime.policy.evaluate("tool_file_read", {"path": str(allowed_file)})
            == Decision.ALLOW
        )
        # Outside sandbox should be forbidden by PathGuard
        assert (
            runtime.policy.evaluate("tool_file_read", {"path": str(outside_file)})
            == Decision.FORBIDDEN
        )

    def test_system_prompt_includes_workdir_confinement(self, tmp_path: Path) -> None:
        config = SubAgentConfig(
            model_name="gpt-4o",
            system_prompt="Base prompt.",
            workdir=str(tmp_path),
        )
        runtime = SubAgentRuntime(config)
        assert len(runtime.messages) == 1
        assert "Base prompt." in runtime.messages[0].content
        assert (
            f"Working directory confinement: {tmp_path}" in runtime.messages[0].content
        )


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

        first_started = asyncio.Event()

        class _HangingRuntime:
            """A mock sub-agent that never completes."""

            def __init__(self, _cfg: SubAgentConfig, **kwargs: object) -> None:
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
        mock_factory: MagicMock,
    ) -> None:
        class _MockProvider2(Provider):
            def __init__(self) -> None:
                self.model = Model(
                    id="gpt-4o",
                    provider_name="openai",
                    max_tokens=4096,
                )
                self.tools = None

            async def stream(
                self,
                messages: list[AgentMessage],
            ) -> AsyncIterator[StreamEvent]:
                yield TextStreamEvent(text="mock")

            def format_messages(
                self,
                messages: list[AgentMessage],
            ) -> list[dict[str, object]]:
                return []

        mock_factory.return_value = _MockProvider2()

        config = SubAgentConfig(model_name="gpt-4o")
        runtime = SubAgentRuntime(config)

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

            async def never_ending(_prompt: str) -> str:
                await asyncio.sleep(3600)
                return "never"

            mock_runtime.run = never_ending
            mock_runtime_cls.return_value = mock_runtime

            with pytest.raises((TimeoutError, asyncio.TimeoutError)):
                await o.spawn(config, "slow task")


class TestSpawnAgentTool:
    """Tests for ``spawn_agent`` tool implementation."""

    @pytest.mark.asyncio
    async def test_spawn_agent_success(self) -> None:
        with patch(
            "agentsx.tools.builtin.orchestration.subagent._get_orchestra"
        ) as mock_get:
            mock_orc = AsyncMock()
            mock_orc.spawn = AsyncMock(return_value="Subagent task output")
            mock_get.return_value = mock_orc

            res = await spawn_agent.call(
                prompt="Analyze data",
                role="leaf",
                max_steps=5,
            )
            assert not res.is_error
            assert "Subagent task output" in res.content
            mock_orc.spawn.assert_called_once()

    @pytest.mark.asyncio
    async def test_spawn_agent_max_depth_exceeded(self) -> None:
        res = await spawn_agent.call(
            prompt="Too deep",
            max_spawn_depth=2,
            current_depth=2,
        )
        assert "maximum spawn depth (2) exceeded" in res.content

    @pytest.mark.asyncio
    async def test_spawn_agent_error_handling(self) -> None:
        with patch(
            "agentsx.tools.builtin.orchestration.subagent._get_orchestra"
        ) as mock_get:
            mock_orc = AsyncMock()
            mock_orc.spawn = AsyncMock(side_effect=RuntimeError("Subagent failed"))
            mock_get.return_value = mock_orc

            res = await spawn_agent.call(prompt="Will fail")
            assert "Sub-agent error: Subagent failed" in res.content

    @pytest.mark.asyncio
    async def test_spawn_agent_invalid_role_fallback(self) -> None:
        with patch(
            "agentsx.tools.builtin.orchestration.subagent._get_orchestra"
        ) as mock_get:
            mock_orc = AsyncMock()
            mock_orc.spawn = AsyncMock(return_value="OK")
            mock_get.return_value = mock_orc

            res = await spawn_agent.call(prompt="Test role", role="nonexistent_role")
            assert not res.is_error
            config_arg = mock_orc.spawn.call_args[0][0]
            assert config_arg.role == SubAgentRole.LEAF

    @pytest.mark.asyncio
    async def test_spawn_agent_with_workdir(self, tmp_path: Path) -> None:
        with patch(
            "agentsx.tools.builtin.orchestration.subagent._get_orchestra"
        ) as mock_get:
            mock_orc = AsyncMock()
            mock_orc.spawn = AsyncMock(return_value="Isolated output")
            mock_get.return_value = mock_orc

            res = await spawn_agent.call(
                prompt="Task in sandbox",
                workdir=str(tmp_path),
            )
            assert not res.is_error
            config_arg = mock_orc.spawn.call_args[0][0]
            assert config_arg.workdir == str(tmp_path)
