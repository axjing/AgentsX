"""Tests for CLI entrypoint and REPL (main.py and repl.py)."""

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from agentsx.cli.main import _async_chat, _async_run, _build_user_message, app
from agentsx.cli.repl import display_tool_event, handle_command
from agentsx.protocol.events import (
    AgentEvent,
    ErrorEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolExecutionEvent,
)
from agentsx.protocol.messages import (
    AgentMessage,
    ContentType,
    MessageRole,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)
from agentsx.session.store import SessionStore

runner = CliRunner()


# ── Typer CLI Help & Option Tests ────────────────────────────────────


class TestCliOptions:
    """CLI top-level and subcommand option tests."""

    def test_cli_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "AgentsX" in result.output
        assert "chat" in result.output
        assert "run" in result.output

    def test_chat_help(self) -> None:
        result = runner.invoke(app, ["chat", "--help"])
        assert result.exit_code == 0
        assert "--model" in result.output
        assert "--system" in result.output
        assert "--no-tools" in result.output
        assert "--backend" in result.output

    def test_run_help(self) -> None:
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--model" in result.output
        assert "--max-steps" in result.output


# ── User Message Building Tests ──────────────────────────────────────


class TestBuildUserMessage:
    """Multimodal and text user message creation."""

    def test_text_only_message(self) -> None:
        msg = _build_user_message("Hello, agent!", [])
        assert msg.role == MessageRole.USER
        assert msg.content == "Hello, agent!"
        assert msg.content_parts is None

    def test_multimodal_message(self, tmp_path: Path) -> None:
        img_file = tmp_path / "test.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\n")
        aud_file = tmp_path / "test.mp3"
        aud_file.write_bytes(b"ID3mockaudio")
        vid_file = tmp_path / "test.mp4"
        vid_file.write_bytes(b"mockvideo")

        msg = _build_user_message(
            "Inspect these files",
            image_paths=[str(img_file)],
            audio_paths=[str(aud_file)],
            video_paths=[str(vid_file)],
        )
        assert msg.role == MessageRole.USER
        assert msg.content == "Inspect these files"
        assert msg.content_parts is not None
        assert len(msg.content_parts) == 4
        assert msg.content_parts[0].type == ContentType.TEXT
        assert msg.content_parts[1].type == ContentType.IMAGE_BASE64
        assert msg.content_parts[2].type == ContentType.AUDIO_BASE64
        assert msg.content_parts[3].type == ContentType.VIDEO_BASE64


# ── REPL Functionality Tests ─────────────────────────────────────────


class TestReplDisplay:
    """Tests for REPL tool display."""

    def test_display_tool_success(self) -> None:
        tc = ToolCall(id="tc-1", name="tool_file_read", arguments={"path": "a.txt"})
        tr = ToolResult(
            tool_call_id="tc-1",
            status=ToolResultStatus.SUCCESS,
            content="File content hello",
        )
        event = ToolExecutionEvent(tool_call=tc, result=tr)
        display_tool_event(event)

    def test_display_tool_error(self) -> None:
        tc = ToolCall(id="tc-2", name="tool_bash", arguments={"command": "cat none"})
        tr = ToolResult(
            tool_call_id="tc-2",
            status=ToolResultStatus.ERROR,
            content="No such file or directory",
        )
        event = ToolExecutionEvent(tool_call=tc, result=tr)
        display_tool_event(event)


class TestReplHandleCommand:
    """Tests for REPL slash commands."""

    def test_handle_help(self) -> None:
        msgs: list[AgentMessage] = []
        new_id, model = handle_command("/help", msgs)
        assert new_id is None

    def test_handle_clear(self) -> None:
        msgs = [AgentMessage(role=MessageRole.USER, content="Hello")]
        new_id, model = handle_command("/clear", msgs)
        assert new_id is None
        assert len(msgs) == 0

    def test_handle_exit(self) -> None:
        msgs: list[AgentMessage] = []
        with pytest.raises(SystemExit):
            handle_command("/exit", msgs)

    def test_handle_unknown_command(self) -> None:
        msgs: list[AgentMessage] = []
        new_id, model = handle_command("/unknown_xyz", msgs)
        assert new_id is None

    def test_handle_new_session(self, tmp_path: Path) -> None:
        store = SessionStore(base_dir=tmp_path / "sessions")
        msgs = [AgentMessage(role=MessageRole.USER, content="old")]
        new_id, model = handle_command(
            "/new",
            msgs,
            store=store,
            session_id="old-id",
            model_name="mock-model",
        )
        assert new_id is not None
        assert new_id != "old-id"


# ── CLI Execution Loop Tests ─────────────────────────────────────────


class TestAsyncRun:
    """Tests for CLI run command."""

    @pytest.mark.asyncio
    async def test_async_run_output(self) -> None:
        mock_provider = MagicMock()
        mock_provider.model.id = "mock-model"

        async def fake_prompt(
            *args: object, **kwargs: object
        ) -> AsyncIterator[AgentEvent]:
            yield ModelRequestEvent(messages=[], model="mock-model")
            tc = ToolCall(
                id="call_1", name="tool_file_read", arguments={"path": "x.txt"}
            )
            tr = ToolResult(
                tool_call_id="call_1",
                status=ToolResultStatus.SUCCESS,
                content="file content",
            )
            yield ToolExecutionEvent(tool_call=tc, result=tr)
            yield ModelResponseEvent(content="Final answer from model", delta=False)

        with patch("agentsx.cli.main.create_provider", return_value=mock_provider):
            with patch(
                "agentsx.agent.harness.AgentHarness.prompt", side_effect=fake_prompt
            ):
                await _async_run(
                    prompt="Hello world",
                    model_name="mock-model",
                    no_tools=True,
                    max_steps=5,
                    allow_all=True,
                    timeout=10.0,
                )

    @pytest.mark.asyncio
    async def test_async_run_error_event(self) -> None:
        mock_provider = MagicMock()
        mock_provider.model.id = "mock-model"

        async def fake_prompt(
            *args: object, **kwargs: object
        ) -> AsyncIterator[AgentEvent]:
            yield ErrorEvent(error=RuntimeError("Simulated failure"), context="test")

        with patch("agentsx.cli.main.create_provider", return_value=mock_provider):
            with patch(
                "agentsx.agent.harness.AgentHarness.prompt", side_effect=fake_prompt
            ):
                await _async_run(
                    prompt="Will fail",
                    model_name="mock-model",
                    no_tools=True,
                    max_steps=5,
                )

    def test_run_command_cli(self) -> None:
        with patch("agentsx.cli.main._async_run", new_callable=AsyncMock) as mock_run:
            result = runner.invoke(
                app, ["run", "Test prompt", "--no-tools", "--allow-all"]
            )
            assert result.exit_code == 0
            mock_run.assert_called_once()


# ── Interactive Chat Loop Tests ──────────────────────────────────────


class TestAsyncChat:
    """Tests for CLI interactive chat session setup and loop."""

    @pytest.mark.asyncio
    async def test_chat_single_turn_and_exit(self, tmp_path: Path) -> None:
        mock_provider = MagicMock()
        mock_provider.model.id = "test-model"

        prompt_inputs: list[str | Exception] = ["What is 1+1?", EOFError()]

        async def fake_prompt_async(prompt: str) -> str:
            val = prompt_inputs.pop(0)
            if isinstance(val, Exception):
                raise val
            return val

        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(side_effect=fake_prompt_async)

        mock_session_factory = MagicMock()
        mock_session_factory.__getitem__.return_value = MagicMock(
            return_value=mock_session
        )
        mock_session_factory.return_value = mock_session

        async def fake_harness_prompt(
            *args: object, **kwargs: object
        ) -> AsyncIterator[AgentEvent]:
            yield ModelRequestEvent(messages=[], model="test-model")
            yield ModelResponseEvent(content="2", delta=True)
            yield ModelResponseEvent(content="2", delta=False)

        with patch("agentsx.cli.main.create_provider", return_value=mock_provider):
            with patch("agentsx.cli.main.PromptSession", mock_session_factory):
                with patch(
                    "agentsx.agent.harness.AgentHarness.prompt",
                    side_effect=fake_harness_prompt,
                ):
                    await _async_chat(
                        model_name="test-model",
                        system_prompt="Be concise",
                        no_tools=True,
                        max_steps=3,
                        allow_all=True,
                        workspace=str(tmp_path),
                        backend="jsonl",
                    )
