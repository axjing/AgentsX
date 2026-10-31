"""MCP server configuration loader and tool registration.

Discovers external MCP server definitions from ./.agentsx/mcp.json
and ~/.agentsx/mcp.json, connects via stdio transport, and registers
discovered tools into ToolRegistry.
"""

import json
import logging
from pathlib import Path
from typing import Any

from agentsx.tools import TOOLSET_MCP, ToolRegistry, ToolSpec
from agentsx.tools.builtin.mcp.mcp_client import MCPClient, MCPServerConfig

logger = logging.getLogger(__name__)


def load_mcp_configs(
    project_dir: Path | None = None,
) -> dict[str, MCPServerConfig]:
    """Load MCP server configs from global and project-level mcp.json files.

    Candidate paths:
        1. ``~/.agentsx/mcp.json`` (user-global)
        2. ``./.agentsx/mcp.json`` (project-specific, overrides global)

    Format::

        {
            "mcpServers": {
                "server-name": {
                    "command": "uvx",
                    "args": ["mcp-server-git"],
                    "env": {"DEBUG": "1"},
                    "timeout": 30.0
                }
            }
        }

    Args:
        project_dir: Root directory of current project. Defaults to Path.cwd().

    Returns:
        Mapping of server names to MCPServerConfig.
    """
    candidates = [
        Path.home() / ".agentsx" / "mcp.json",
        (project_dir or Path.cwd()) / ".agentsx" / "mcp.json",
    ]

    configs: dict[str, MCPServerConfig] = {}

    for config_path in candidates:
        if not config_path.is_file():
            continue
        try:
            content = config_path.read_text(encoding="utf-8")
            data = json.loads(content)
            servers = data.get("mcpServers", {})
            if not isinstance(servers, dict):
                continue

            for name, s_cfg in servers.items():
                if not isinstance(s_cfg, dict):
                    continue
                command = s_cfg.get("command")
                if not command or not isinstance(command, str):
                    continue
                args = s_cfg.get("args")
                arg_list = [str(a) for a in args] if isinstance(args, list) else None
                env = s_cfg.get("env")
                env_dict = (
                    {str(k): str(v) for k, v in env.items()}
                    if isinstance(env, dict)
                    else None
                )
                timeout = float(s_cfg.get("timeout", 30.0))

                configs[name] = MCPServerConfig(
                    command=command,
                    args=arg_list,
                    env=env_dict,
                    timeout=timeout,
                )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to load MCP config from %s: %s", config_path, exc)

    return configs


async def register_mcp_servers(
    registry: ToolRegistry,
    configs: dict[str, MCPServerConfig],
) -> list[str]:
    """Connect to configured MCP servers and register their tools.

    Args:
        registry: The ToolRegistry to register discovered tools into.
        configs: Dictionary mapping server names to MCPServerConfig.

    Returns:
        List of successfully connected server names.
    """
    connected_servers: list[str] = []

    for server_name, cfg in configs.items():
        client = MCPClient(cfg)
        try:
            await client.connect()
            tools = await client.list_tools()

            for t in tools:
                raw_name = str(t.get("name", ""))
                if not raw_name:
                    continue
                desc = str(t.get("description", f"MCP tool from {server_name}"))
                schema = t.get("inputSchema")
                schema_dict = schema if isinstance(schema, dict) else {}

                tool_name = (
                    raw_name
                    if raw_name.startswith("mcp_")
                    else f"mcp_{server_name}_{raw_name}"
                )

                async def _make_caller(
                    _client: MCPClient = client,
                    _name: str = raw_name,
                    **kwargs: Any,
                ) -> str:
                    return await _client.call_tool(_name, kwargs)

                spec = ToolSpec(
                    name=tool_name,
                    description=desc,
                    fn=_make_caller,
                    parameters=schema_dict,
                    toolset=TOOLSET_MCP,
                )
                registry.register(spec)

            connected_servers.append(server_name)
            logger.info(
                "Connected MCP server '%s' (%d tools registered)",
                server_name,
                len(tools),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to connect MCP server '%s': %s",
                server_name,
                exc,
            )

    return connected_servers
