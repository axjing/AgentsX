"""Tool registry and built-in tools.

Usage::

    registry = ToolRegistry()
    registry.register(read_tool)
    registry.call("read", path="/tmp/foo.txt")

Toolset support (inspired by Hermes-Agent's toolset composition):
    Tools can be grouped into named toolsets for enable/disable::

        @tool(description="Read a file", toolset="read")
        def read(path: str) -> str: ...

        registry.enable_toolset("read")
        registry.disable_toolset("write")
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, TypeVar

from agentsx.core.errors import ToolError

_F = TypeVar("_F", bound=Callable[..., Any])

# ── Predefined toolset names ────────────────────────────────

TOOLSET_READ = "read"
"""Read-only file and data inspection tools."""

TOOLSET_WRITE = "write"
"""File modification and creation tools."""

TOOLSET_EXEC = "exec"
"""Shell/command execution tools."""

TOOLSET_WEB = "web"
"""Web search and fetch tools."""

TOOLSET_ORCHESTRATION = "orchestration"
"""Sub-agent and delegation tools."""

TOOLSET_VISION = "vision"
"""Image analysis tools."""

ALL_TOOLSETS = frozenset(
    {
        TOOLSET_READ,
        TOOLSET_WRITE,
        TOOLSET_EXEC,
        TOOLSET_WEB,
        TOOLSET_ORCHESTRATION,
        TOOLSET_VISION,
    }
)


class ToolSpec:
    """Describes a tool that an LLM can invoke."""

    def __init__(
        self,
        name: str,
        description: str,
        fn: Callable[..., Any],
        parameters: dict[str, object] | None = None,
        check_fn: Callable[[], bool] | None = None,
        toolset: str = "",
    ) -> None:
        self.name = name
        self.description = description
        self.fn = fn
        self.parameters = parameters or _json_schema(fn)
        self.check_fn = check_fn or (lambda: True)
        self.toolset = toolset

    def to_openai_format(self) -> dict[str, object]:
        """Return an OpenAI-compatible tool definition dict."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic_format(self) -> dict[str, object]:
        """Return an Anthropic-compatible tool definition dict."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }

    async def call(self, **kwargs: object) -> str:
        """Execute the tool and return the result as a string."""
        try:
            result = self.fn(**kwargs)
            if inspect.iscoroutine(result):
                result = await result
            return str(result)
        except Exception as exc:
            raise ToolError(
                f"Tool '{self.name}' failed: {exc}",
            ) from exc


class ToolRegistry:
    """Manages a collection of ToolSpecs with toolset support.

    Toolsets allow grouping tools into named categories for
    enable/disable.  Only tools from enabled toolsets are
    exposed to the LLM.

    When no toolsets are explicitly enabled, all tools are
    visible (backward-compatible default).
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._enabled_toolsets: set[str] = set()
        self._toolset_mode: bool = False
        """When True, only tools from enabled toolsets are listed."""

    # ── Registration ─────────────────────────────────────────

    def register(self, tool: ToolSpec) -> None:
        """Register a tool by name."""
        self._tools[tool.name] = tool

    def register_all(self, *tools: ToolSpec) -> None:
        """Register multiple tools at once."""
        for t in tools:
            self.register(t)

    # ── Toolset management ───────────────────────────────────

    def enable_toolset(self, name: str) -> None:
        """Enable a toolset. Activates toolset filtering mode."""
        self._toolset_mode = True
        self._enabled_toolsets.add(name)

    def disable_toolset(self, name: str) -> None:
        """Disable a toolset."""
        self._enabled_toolsets.discard(name)

    def enable_all_toolsets(self) -> None:
        """Enable all known toolsets and disable filtering."""
        self._toolset_mode = False
        self._enabled_toolsets.clear()

    def is_toolset_enabled(self, name: str) -> bool:
        """Check if a toolset is enabled."""
        if not self._toolset_mode:
            return True
        return name in self._enabled_toolsets

    def list_enabled_toolsets(self) -> list[str]:
        """Return names of all enabled toolsets."""
        return sorted(self._enabled_toolsets)

    # ── Lookup and execution ─────────────────────────────────

    def get(self, name: str) -> ToolSpec | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    async def call(self, name: str, **kwargs: object) -> str:
        """Look up and call a tool by name."""
        tool = self.get(name)
        if tool is None:
            raise ToolError(f"Unknown tool: '{name}'")
        return await tool.call(**kwargs)

    # ── Listing (respects toolset filters) ───────────────────

    def list_tools(self) -> list[ToolSpec]:
        """Return all registered tools, filtered by enabled toolsets."""
        if not self._toolset_mode:
            return list(self._tools.values())
        return [
            t
            for t in self._tools.values()
            if not t.toolset or t.toolset in self._enabled_toolsets
        ]

    def to_openai_tools(self) -> list[dict[str, object]]:
        """Return OpenAI-compatible tool definitions, filtered by check_fn + toolset."""
        return [
            t.to_openai_format()
            for t in self._tools.values()
            if t.check_fn() and self._is_visible(t)
        ]

    def to_anthropic_tools(self) -> list[dict[str, object]]:
        """Anthropic tool definitions, filtered by check_fn + toolset."""
        return [
            t.to_anthropic_format()
            for t in self._tools.values()
            if t.check_fn() and self._is_visible(t)
        ]

    def _is_visible(self, tool: ToolSpec) -> bool:
        """Check if a tool should be visible to the LLM."""
        if not self._toolset_mode:
            return True
        if not tool.toolset:
            return True
        return tool.toolset in self._enabled_toolsets

    # ── Toolset info ─────────────────────────────────────────

    def list_toolsets(self) -> dict[str, list[ToolSpec]]:
        """Return all tools grouped by toolset."""
        groups: dict[str, list[ToolSpec]] = {}
        for t in self._tools.values():
            ts = t.toolset or "_ungrouped"
            groups.setdefault(ts, []).append(t)
        return groups


def tool(
    name: str | None = None,
    description: str | None = None,
    check_fn: Callable[[], bool] | None = None,
    toolset: str = "",
) -> Callable[[_F], ToolSpec]:
    """Decorator that wraps a function into a ``ToolSpec``.

    Usage::

        @tool(description="Read a file", toolset="read")
        def read(path: str) -> str: ...

        @tool(description="LSP diagnostics", check_fn=lambda: has_lsp())
        def lsp_diagnostics(path: str) -> str: ...
    """

    def decorator(fn: _F) -> ToolSpec:
        tool_name = name if name is not None else fn.__name__
        tool_desc = description if description is not None else (fn.__doc__ or "")
        return ToolSpec(
            name=tool_name,
            description=tool_desc,
            fn=fn,
            check_fn=check_fn,
            toolset=toolset,
        )

    return decorator


# ── Helpers ────────────────────────────────────────────────────────────

_JSON_TYPE_MAP: dict[str, str] = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "None": "null",
    "NoneType": "null",
    "list": "array",
    "dict": "object",
}


def _json_schema(fn: Callable[..., Any]) -> dict[str, object]:
    """Derive a minimal JSON schema from a function's signature.

    Handles `X | Y` unions (Python 3.10+), `typing.Union`,
    `typing.Optional`, and generic containers (`list[str]`, `dict[str, int]`).
    """
    import sys  # noqa: PLC0415
    import types  # noqa: PLC0415
    import typing  # noqa: PLC0415

    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return {"type": "object", "properties": {}}

    properties: dict[str, object] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue

        annotation = param.annotation
        is_optional = False

        if annotation is inspect.Parameter.empty:
            json_type = "string"
        else:
            # Detect Union[X, None] / Optional[X] / X | None
            origin = getattr(annotation, "__origin__", None)
            is_union_type = origin is typing.Union or (
                sys.version_info >= (3, 10) and origin is types.UnionType
            )

            if is_union_type:
                args = typing.get_args(annotation)
                non_none = [a for a in args if a is not type(None)]
                if len(non_none) < len(args):
                    is_optional = True
                if len(non_none) == 1:
                    inner = non_none[0]
                    json_type = _schema_type_for(inner)
                else:
                    json_type = _schema_type_for(non_none[0] if non_none else str)
            else:
                json_type = _schema_type_for(annotation)

        # Parameters with default values or Optional types are not required
        if param.default is inspect.Parameter.empty and not is_optional:
            required.append(param_name)

        properties[param_name] = {"type": json_type}

    return {"type": "object", "properties": properties, "required": required}


def _schema_type_for(annotation: type) -> str:
    """Map a Python type annotation to a JSON Schema type string."""
    origin = getattr(annotation, "__origin__", None)
    if origin:
        return _JSON_TYPE_MAP.get(origin.__name__, "string")
    type_name = getattr(annotation, "__name__", str(annotation))
    return _JSON_TYPE_MAP.get(type_name, "string")
