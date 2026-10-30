"""MCP (Model Context Protocol) client tool.

Connects to external MCP servers via stdio transport.
"""

import asyncio
import json
import shutil
from dataclasses import dataclass
from typing import Any

from agentsx.tools import TOOLSET_MCP, tool


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server connection."""

    command: str
    args: list[str] | None = None
    env: dict[str, str] | None = None
    timeout: float = 30.0


class MCPClient:
    """Lightweight asynchronous MCP client for stdio transport."""

    def __init__(self, config: MCPServerConfig) -> None:
        self._config = config
        self._process: asyncio.subprocess.Process | None = None
        self._message_id = 0

    async def connect(self) -> None:
        """Start the MCP server subprocess and perform handshake.

        Raises:
            ConnectionError: If subprocess fails to start or stream is unavailable.
        """
        cmd = shutil.which(self._config.command) or self._config.command
        args = [cmd] + (self._config.args or [])
        self._process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._config.env,
        )
        await self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "agentsx",
                    "version": "0.1.0",
                },
            },
        )
        await self._send_notification("notifications/initialized")

    async def disconnect(self) -> None:
        """Stop the MCP server subprocess."""
        if self._process is not None:
            try:
                if self._process.returncode is None:
                    self._process.terminate()
                    try:
                        await asyncio.wait_for(self._process.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        self._process.kill()
                        await self._process.wait()
            except ProcessLookupError:
                pass
            finally:
                self._process = None

    async def __aenter__(self) -> "MCPClient":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Async context manager exit."""
        await self.disconnect()

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools on the MCP server.

        Returns:
            List of tool descriptions from the server.
        """
        result = await self._send_request("tools/list", {})
        tools = result.get("tools", [])
        if isinstance(tools, list):
            return [t for t in tools if isinstance(t, dict)]
        return []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Call a tool on the MCP server.

        Args:
            name: The tool name to invoke.
            arguments: Tool arguments dictionary.

        Returns:
            Output content from the tool invocation.
        """
        result = await self._send_request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )
        content = result.get("content", [])
        if not content:
            if "text" in result:
                return str(result["text"])
            return "(no output)"
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(parts) if parts else "(no output)"

    async def _send_notification(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self._process or not self._process.stdin:
            return
        notification: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            notification["params"] = params
        payload = json.dumps(notification) + "\n"
        self._process.stdin.write(payload.encode())
        await self._process.stdin.drain()

    async def _send_request(
        self,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and await the response.

        Args:
            method: JSON-RPC method name.
            params: Parameters dictionary.

        Returns:
            The result dictionary from JSON-RPC response.

        Raises:
            ConnectionError: If not connected or connection is closed unexpectedly.
            RuntimeError: If server responds with a JSON-RPC error.
            asyncio.TimeoutError: If reading response exceeds timeout.
        """
        if not self._process or not self._process.stdin or not self._process.stdout:
            raise ConnectionError("MCP server not connected")
        self._message_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._message_id,
            "method": method,
            "params": params,
        }
        payload = json.dumps(request) + "\n"
        self._process.stdin.write(payload.encode())
        await self._process.stdin.drain()

        while True:
            line = await asyncio.wait_for(
                self._process.stdout.readline(),
                timeout=self._config.timeout,
            )
            if not line:
                raise ConnectionError(
                    "MCP server process closed connection unexpectedly"
                )
            line_str = line.decode().strip()
            if not line_str:
                continue
            try:
                data = json.loads(line_str)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("id") == self._message_id:
                if "error" in data:
                    err = data["error"]
                    err_msg = (
                        err.get("message", str(err))
                        if isinstance(err, dict)
                        else str(err)
                    )
                    raise RuntimeError(f"MCP server error: {err_msg}")
                result_val = data.get("result", {})
                if isinstance(result_val, dict):
                    return result_val
                return {}


@tool(
    description="Call a tool on an external MCP server (stdio transport).",
    toolset=TOOLSET_MCP,
)
async def tool_mcp_call(
    server_command: str,
    tool_name: str,
    arguments: str = "{}",
    server_args: str = "",
    timeout: float = 30.0,
) -> str:
    """Call a tool on an external MCP server.

    Args:
        server_command: Command to start the MCP server.
        tool_name: Name of the tool to call.
        arguments: JSON string of tool arguments.
        server_args: Space-separated arguments for the server command.
        timeout: Timeout in seconds for the MCP server call.

    Returns:
        The tool result as text.
    """
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError:
        return f"Error: invalid arguments JSON: {arguments}"
    if not isinstance(args, dict):
        return f"Error: arguments must be a JSON object, got {type(args).__name__}"

    server_arg_list = server_args.split() if server_args else []
    config = MCPServerConfig(
        command=server_command,
        args=server_arg_list,
        timeout=timeout,
    )
    client = MCPClient(config)
    try:
        await client.connect()
        return await client.call_tool(tool_name, args)
    except (ConnectionError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        return f"MCP error: {exc}"
    except asyncio.TimeoutError:
        return f"MCP error: operation timed out after {timeout}s"
    finally:
        await client.disconnect()
