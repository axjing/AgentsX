"""Tests for MCP (Model Context Protocol) async client and tool."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentsx.security.policy import Decision, ExecutionPolicy
from agentsx.tools import ToolRegistry
from agentsx.tools.builtin.mcp import (
    MCPClient,
    MCPServerConfig,
    load_mcp_configs,
    register_mcp_servers,
    tool_mcp_call,
)


class DummyProcess:
    """Mock asyncio subprocess with StreamReader stdout and AsyncMock stdin."""

    def __init__(self) -> None:
        self.stdin = AsyncMock()
        self.stdin.write = MagicMock()
        self.stdin.drain = AsyncMock()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.returncode: int | None = None
        self.terminate_called = False
        self.kill_called = False

    def terminate(self) -> None:
        self.terminate_called = True
        self.returncode = -15

    def kill(self) -> None:
        self.kill_called = True
        self.returncode = -9

    async def wait(self) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


# ── MCPServerConfig Tests ────────────────────────────────────────────


class TestMCPServerConfig:
    """Configuration tests for MCPServerConfig."""

    def test_default_config(self) -> None:
        cfg = MCPServerConfig(command="python")
        assert cfg.command == "python"
        assert cfg.args is None
        assert cfg.env is None
        assert cfg.timeout == 30.0

    def test_custom_config(self) -> None:
        cfg = MCPServerConfig(
            command="node",
            args=["server.js", "--verbose"],
            env={"PORT": "8080"},
            timeout=10.0,
        )
        assert cfg.command == "node"
        assert cfg.args == ["server.js", "--verbose"]
        assert cfg.env == {"PORT": "8080"}
        assert cfg.timeout == 10.0


# ── MCPClient Lifecycle & Handshake Tests ────────────────────────────


class TestMCPClientLifecycle:
    """Lifecycle and handshake tests for MCPClient."""

    @pytest.mark.asyncio
    async def test_connect_and_handshake(self) -> None:
        mock_proc = DummyProcess()
        # Feed response for 'initialize' request (id=1)
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "test-server", "version": "1.0"},
            },
        }
        mock_proc.stdout.feed_data((json.dumps(init_response) + "\n").encode())

        cfg = MCPServerConfig(command="mock-server")
        client = MCPClient(cfg)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await client.connect()

            # Verify handshake request was written
            assert mock_proc.stdin.write.call_count >= 2
            first_call = mock_proc.stdin.write.call_args_list[0][0][0].decode()
            assert '"method": "initialize"' in first_call

            # Verify notification was sent
            second_call = mock_proc.stdin.write.call_args_list[1][0][0].decode()
            assert '"method": "notifications/initialized"' in second_call

            await client.disconnect()
            assert mock_proc.terminate_called

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        mock_proc = DummyProcess()
        init_resp = {"jsonrpc": "2.0", "id": 1, "result": {}}
        mock_proc.stdout.feed_data((json.dumps(init_resp) + "\n").encode())

        cfg = MCPServerConfig(command="mock-server")
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            async with MCPClient(cfg) as client:
                assert client._process is not None
            assert client._process is None
            assert mock_proc.terminate_called

    @pytest.mark.asyncio
    async def test_call_tool_success(self) -> None:
        mock_proc = DummyProcess()
        # Init handshake response (id=1)
        init_resp = {"jsonrpc": "2.0", "id": 1, "result": {}}
        # Tool call response (id=2)
        tool_resp = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "content": [
                    {"type": "text", "text": "result-line-1"},
                    {"type": "text", "text": "result-line-2"},
                ]
            },
        }
        mock_proc.stdout.feed_data((json.dumps(init_resp) + "\n").encode())
        mock_proc.stdout.feed_data((json.dumps(tool_resp) + "\n").encode())

        cfg = MCPServerConfig(command="mock-server")
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            async with MCPClient(cfg) as client:
                output = await client.call_tool("calc", {"expr": "1+1"})
                assert output == "result-line-1\nresult-line-2"

    @pytest.mark.asyncio
    async def test_call_tool_server_error(self) -> None:
        mock_proc = DummyProcess()
        init_resp = {"jsonrpc": "2.0", "id": 1, "result": {}}
        tool_err = {
            "jsonrpc": "2.0",
            "id": 2,
            "error": {"code": -32602, "message": "Unknown tool: foo"},
        }
        mock_proc.stdout.feed_data((json.dumps(init_resp) + "\n").encode())
        mock_proc.stdout.feed_data((json.dumps(tool_err) + "\n").encode())

        cfg = MCPServerConfig(command="mock-server")
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            async with MCPClient(cfg) as client:
                with pytest.raises(RuntimeError, match="Unknown tool: foo"):
                    await client.call_tool("foo", {})

    @pytest.mark.asyncio
    async def test_list_tools(self) -> None:
        mock_proc = DummyProcess()
        init_resp = {"jsonrpc": "2.0", "id": 1, "result": {}}
        list_resp = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [
                    {"name": "test_tool", "description": "A test tool"},
                ]
            },
        }
        mock_proc.stdout.feed_data((json.dumps(init_resp) + "\n").encode())
        mock_proc.stdout.feed_data((json.dumps(list_resp) + "\n").encode())

        cfg = MCPServerConfig(command="mock-server")
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            async with MCPClient(cfg) as client:
                tools = await client.list_tools()
                assert len(tools) == 1
                assert tools[0]["name"] == "test_tool"

    @pytest.mark.asyncio
    async def test_skips_non_json_lines(self) -> None:
        mock_proc = DummyProcess()
        init_resp = {"jsonrpc": "2.0", "id": 1, "result": {}}
        tool_resp = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"content": [{"type": "text", "text": "success"}]},
        }
        mock_proc.stdout.feed_data(b"[INFO] Starting MCP server...\n")
        mock_proc.stdout.feed_data((json.dumps(init_resp) + "\n").encode())
        mock_proc.stdout.feed_data(b"\n")
        mock_proc.stdout.feed_data(b"[DEBUG] Executing tool...\n")
        mock_proc.stdout.feed_data((json.dumps(tool_resp) + "\n").encode())

        cfg = MCPServerConfig(command="mock-server")
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            async with MCPClient(cfg) as client:
                result = await client.call_tool("my_tool", {})
                assert result == "success"

    @pytest.mark.asyncio
    async def test_eof_raises_connection_error(self) -> None:
        mock_proc = DummyProcess()
        init_resp = {"jsonrpc": "2.0", "id": 1, "result": {}}
        mock_proc.stdout.feed_data((json.dumps(init_resp) + "\n").encode())
        mock_proc.stdout.feed_eof()

        cfg = MCPServerConfig(command="mock-server")
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            async with MCPClient(cfg) as client:
                with pytest.raises(ConnectionError, match="unexpectedly"):
                    await client.call_tool("echo", {})

    @pytest.mark.asyncio
    async def test_not_connected_raises_error(self) -> None:
        cfg = MCPServerConfig(command="mock-server")
        client = MCPClient(cfg)
        with pytest.raises(ConnectionError, match="not connected"):
            await client.call_tool("echo", {})


# ── tool_mcp_call Function Tests ─────────────────────────────────────


class TestToolMcpCall:
    """Tests for tool_mcp_call function wrapper."""

    @pytest.mark.asyncio
    async def test_invalid_arguments_json(self) -> None:
        res = await tool_mcp_call.call(
            server_command="my-server",
            tool_name="echo",
            arguments="{bad json",
        )
        assert "Error: invalid arguments JSON" in res.content

    @pytest.mark.asyncio
    async def test_non_dict_arguments_json(self) -> None:
        res = await tool_mcp_call.call(
            server_command="my-server",
            tool_name="echo",
            arguments="[1, 2, 3]",
        )
        assert "Error: arguments must be a JSON object" in res.content

    @pytest.mark.asyncio
    async def test_successful_tool_call(self) -> None:
        mock_proc = DummyProcess()
        init_resp = {"jsonrpc": "2.0", "id": 1, "result": {}}
        tool_resp = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"content": [{"type": "text", "text": "hello mcp"}]},
        }
        mock_proc.stdout.feed_data((json.dumps(init_resp) + "\n").encode())
        mock_proc.stdout.feed_data((json.dumps(tool_resp) + "\n").encode())

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            res = await tool_mcp_call.call(
                server_command="my-server",
                tool_name="greeting",
                arguments='{"name": "world"}',
            )
            assert res.content == "hello mcp"

    @pytest.mark.asyncio
    async def test_timeout_handling(self) -> None:
        mock_proc = DummyProcess()
        # Feed nothing to cause wait_for to time out
        cfg = MCPServerConfig(command="my-server", timeout=0.01)
        client = MCPClient(cfg)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with pytest.raises(asyncio.TimeoutError):
                await client.connect()

    @pytest.mark.asyncio
    async def test_tool_call_timeout_wrapper(self) -> None:
        mock_proc = DummyProcess()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            res = await tool_mcp_call.call(
                server_command="my-server",
                tool_name="echo",
                timeout=0.01,
            )
            assert "operation timed out" in res.content


# ── ExecutionPolicy MCP Security Tests ───────────────────────────────


class TestMCPSecurity:
    """Security integration tests for MCP calls."""

    def test_default_policy_prompts_for_mcp(self) -> None:
        policy = ExecutionPolicy.default()
        decision = policy.evaluate(
            "tool_mcp_call",
            {"server_command": "npx -y @modelcontextprotocol/server-sqlite"},
        )
        assert decision == Decision.PROMPT

    def test_policy_forbids_dangerous_command_in_mcp(self) -> None:
        policy = ExecutionPolicy.default()
        decision = policy.evaluate(
            "tool_mcp_call",
            {"server_command": "rm -rf /"},
        )
        assert decision == Decision.FORBIDDEN


# ── MCP Config Loader and Discovery Tests ─────────────────────────────


class TestMCPConfigLoader:
    """Tests for load_mcp_configs."""

    def test_load_mcp_configs_empty(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path / "proj")  # type: ignore[attr-defined]
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")  # type: ignore[attr-defined]
        configs = load_mcp_configs()
        assert configs == {}

    def test_load_mcp_configs_valid(self, tmp_path: Path, monkeypatch: object) -> None:
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir(parents=True)
        home_dir = tmp_path / "home"
        home_dir.mkdir(parents=True)
        monkeypatch.setattr(Path, "cwd", lambda: proj_dir)  # type: ignore[attr-defined]
        monkeypatch.setattr(Path, "home", lambda: home_dir)  # type: ignore[attr-defined]

        mcp_file = proj_dir / ".agentsx" / "mcp.json"
        mcp_file.parent.mkdir(parents=True)
        mcp_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "sqlite": {
                            "command": "uvx",
                            "args": ["mcp-server-sqlite", "--db", "test.db"],
                            "env": {"DEBUG": "1"},
                            "timeout": 45.0,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        configs = load_mcp_configs()
        assert "sqlite" in configs
        cfg = configs["sqlite"]
        assert cfg.command == "uvx"
        assert cfg.args == ["mcp-server-sqlite", "--db", "test.db"]
        assert cfg.env == {"DEBUG": "1"}
        assert cfg.timeout == 45.0

    def test_load_mcp_configs_invalid_json(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir(parents=True)
        monkeypatch.setattr(Path, "cwd", lambda: proj_dir)  # type: ignore[attr-defined]
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")  # type: ignore[attr-defined]

        mcp_file = proj_dir / ".agentsx" / "mcp.json"
        mcp_file.parent.mkdir(parents=True)
        mcp_file.write_text("{malformed: json", encoding="utf-8")

        configs = load_mcp_configs()
        assert configs == {}


class TestMCPRegistration:
    """Tests for register_mcp_servers."""

    @pytest.mark.asyncio
    async def test_register_mcp_servers_success(self) -> None:
        registry = ToolRegistry()
        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client.list_tools = AsyncMock(
            return_value=[
                {
                    "name": "fetch_data",
                    "description": "Fetch database rows",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                    },
                }
            ]
        )
        mock_client.call_tool = AsyncMock(return_value="row1, row2")

        with patch(
            "agentsx.tools.builtin.mcp.config_loader.MCPClient",
            return_value=mock_client,
        ):
            configs = {
                "db": MCPServerConfig(command="sqlite-mcp"),
            }
            connected = await register_mcp_servers(registry, configs)
            assert connected == ["db"]

            tool = registry.get("mcp_db_fetch_data")
            assert tool is not None
            assert tool.description == "Fetch database rows"

            res = await tool.call(query="SELECT 1")
            assert not res.is_error
            assert res.content == "row1, row2"
            mock_client.call_tool.assert_called_once_with(
                "fetch_data",
                {"query": "SELECT 1"},
            )

