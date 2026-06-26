"""MCP (Model Context Protocol) client tool.

Connects to external MCP servers via stdio transport.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any

from agentsx.tools import tool


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server connection."""

    command: str
    args: list[str] | None = None
    env: dict[str, str] | None = None
    timeout: float = 30.0


class MCPClient:
    """Lightweight MCP client for stdio transport."""

    def __init__(self, config: MCPServerConfig) -> None:
        self._config = config
        self._process: subprocess.Popen[bytes] | None = None
        self._message_id = 0

    def connect(self) -> None:
        """Start the MCP server subprocess."""
        args = [self._config.command] + (self._config.args or [])
        self._process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._send_request("initialize", {"protocolVersion": "2024-11-05"})

    def disconnect(self) -> None:
        """Stop the MCP server subprocess."""
        if self._process:
            self._process.terminate()
            self._process = None

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Call a tool on the MCP server."""
        result = self._send_request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )
        content = result.get("content", [])
        if not content:
            return "(no output)"
        parts = []
        for item in content:
            if item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "\n".join(parts)

    def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request and read the response."""
        if not self._process or not self._process.stdin:
            raise ConnectionError("MCP server not connected")
        self._message_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._message_id,
            "method": method,
            "params": params,
        }
        self._process.stdin.write((json.dumps(request) + "\n").encode())
        self._process.stdin.flush()
        if self._process.stdout:
            response_line = self._process.stdout.readline()
            if response_line:
                parsed = json.loads(response_line.decode())
            result_val = parsed.get("result")
            if isinstance(result_val, dict):
                return result_val
            return {}
        return {}


@tool(description="Call a tool on an external MCP server (stdio transport).")
def tool_mcp_call(
    server_command: str,
    tool_name: str,
    arguments: str = "{}",
    server_args: str = "",
) -> str:
    """Call a tool on an external MCP server.

    Args:
        server_command: Command to start the MCP server.
        tool_name: Name of the tool to call.
        arguments: JSON string of tool arguments.
        server_args: Space-separated arguments for the server command.

    Returns:
        The tool result as text.
    """
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError:
        return f"Error: invalid arguments JSON: {arguments}"
    server_arg_list = server_args.split() if server_args else []
    config = MCPServerConfig(command=server_command, args=server_arg_list)
    client = MCPClient(config)
    try:
        client.connect()
        return client.call_tool(tool_name, args)
    except (ConnectionError, OSError, json.JSONDecodeError) as exc:
        return f"MCP error: {exc}"
    finally:
        client.disconnect()
