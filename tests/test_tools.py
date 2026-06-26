"""Tests for tool system: ToolSpec, ToolRegistry, decorator, built-ins."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agentsx.core.errors import ToolError
from agentsx.tools import ToolRegistry, ToolSpec, tool
from agentsx.tools.builtin import ALL_TOOLS
from agentsx.tools.builtin.read.filesystem import (
    tool_file_glob,
    tool_file_read,
)
from agentsx.tools.builtin.write.filesystem import tool_file_write

# ── ToolSpec ─────────────────────────────────────────────────────────


class TestToolSpec:
    """ToolSpec construction and conversion."""

    def test_basic(self) -> None:
        def dummy(arg1: str, arg2: int = 0) -> str:
            return f"{arg1}:{arg2}"

        spec = ToolSpec(name="dummy", description="A test tool", fn=dummy)
        assert spec.name == "dummy"
        assert spec.description == "A test tool"

        openai_def = spec.to_openai_format()
        assert openai_def["type"] == "function"
        func: dict[str, object] = openai_def["function"]
        assert func["name"] == "dummy"
        params: dict[str, object] = func["parameters"]
        assert "arg1" in params["properties"]

    @pytest.mark.asyncio
    async def test_call_sync(self) -> None:
        def add(a: int, b: int) -> int:
            return a + b

        spec = ToolSpec(name="add", description="Add two numbers", fn=add)
        result = await spec.call(a=1, b=2)
        assert result == "3"

    @pytest.mark.asyncio
    async def test_call_async(self) -> None:
        async def slow_add(a: int, b: int) -> int:
            return a + b

        spec = ToolSpec(name="sadd", description="Slow add", fn=slow_add)
        result = await spec.call(a=10, b=20)
        assert result == "30"

    @pytest.mark.asyncio
    async def test_call_raises_tool_error(self) -> None:
        def broken() -> str:
            msg = "internal"
            raise ValueError(msg)

        spec = ToolSpec(name="broken", description="Broken tool", fn=broken)
        with pytest.raises(ToolError, match="broken"):
            await spec.call()

    def test_check_fn_default(self) -> None:
        def always_true() -> bool:
            return True

        spec = ToolSpec(name="t", description="", fn=lambda: "", check_fn=always_true)
        assert spec.check_fn() is True

    def test_check_fn_filters_tools(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolSpec(name="visible", description="", fn=lambda: "ok"),
        )
        registry.register(
            ToolSpec(
                name="hidden", description="", fn=lambda: "ok", check_fn=lambda: False
            ),
        )
        tools = registry.to_openai_tools()
        names = [t["function"]["name"] for t in tools]
        assert "visible" in names
        assert "hidden" not in names


# ── ToolRegistry ─────────────────────────────────────────────────────


class TestToolRegistry:
    """Registry management."""

    def test_register_and_get(self) -> None:
        registry = ToolRegistry()
        spec = ToolSpec(name="test", description="Test", fn=lambda: "ok")
        registry.register(spec)
        assert registry.get("test") is spec
        assert registry.get("unknown") is None

    def test_register_all(self) -> None:
        registry = ToolRegistry()
        a = ToolSpec(name="a", description="A", fn=lambda: "a")
        b = ToolSpec(name="b", description="B", fn=lambda: "b")
        registry.register_all(a, b)
        assert registry.get("a") is a
        assert registry.get("b") is b

    def test_list_tools(self) -> None:
        registry = ToolRegistry()
        a = ToolSpec(name="a", description="A", fn=lambda: "a")
        registry.register(a)
        tools = registry.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "a"

    @pytest.mark.asyncio
    async def test_call_unknown_tool(self) -> None:
        registry = ToolRegistry()
        with pytest.raises(ToolError, match="Unknown tool"):
            await registry.call("nope")

    def test_to_openai_tools(self) -> None:
        registry = ToolRegistry()
        spec = ToolSpec(
            name="greet",
            description="Greet someone",
            fn=lambda name: f"Hi {name}",
        )
        registry.register(spec)
        tools = registry.to_openai_tools()
        assert len(tools) == 1
        func: dict[str, object] = tools[0]["function"]
        assert func["name"] == "greet"


# ── Decorator ────────────────────────────────────────────────────────


class TestToolDecorator:
    """``@tool`` decorator behaviour."""

    def test_decorator_no_args(self) -> None:
        @tool()
        def hello(name: str) -> str:
            """Say hello."""
            return f"Hello {name}"

        assert isinstance(hello, ToolSpec)
        assert hello.name == "hello"
        assert hello.description == "Say hello."

    def test_decorator_with_args(self) -> None:
        @tool(name="my_greet", description="A greeting")
        def greet(name: str) -> str:
            return f"Hi {name}"

        assert greet.name == "my_greet"
        assert greet.description == "A greeting"

    @pytest.mark.asyncio
    async def test_decorator_callable(self) -> None:
        @tool(description="Add numbers")
        def add(a: int, b: int) -> int:
            return a + b

        result = await add.call(a=3, b=4)
        assert result == "7"

    def test_decorator_with_check_fn(self) -> None:
        @tool(description="Conditional tool", check_fn=lambda: False)
        def conditional() -> str:
            return "never"

        assert isinstance(conditional, ToolSpec)
        assert conditional.check_fn() is False


# ── Built-in: Filesystem ─────────────────────────────────────────────


class TestToolFileRead:
    """Read tool with real files."""

    @pytest.mark.asyncio
    async def test_read_existing(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("line1\nline2\nline3\n")
            tmp = f.name
        try:
            result = await tool_file_read.call(path=tmp)
            assert "line1" in result
            assert "line2" in result
            assert "line3" in result
        finally:
            Path(tmp).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_read_missing(self) -> None:
        result = await tool_file_read.call(path="/nonexistent/file.txt")
        assert "file not found" in result

    @pytest.mark.asyncio
    async def test_read_with_offset(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("a\nb\nc\nd\n")
            tmp = f.name
        try:
            result = await tool_file_read.call(path=tmp, offset=3)
            lines = result.strip().split("\n")
            assert lines[0].startswith("3: c")
        finally:
            Path(tmp).unlink(missing_ok=True)


class TestToolFileWrite:
    """Write tool with real files."""

    @pytest.mark.asyncio
    async def test_write_new_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "new.txt"
            result = await tool_file_write.call(
                path=str(path),
                content="hello world",
            )
            assert "Wrote" in result
            assert path.read_text() == "hello world"

    @pytest.mark.asyncio
    async def test_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "data.txt"
            path.write_text("old")
            result = await tool_file_write.call(
                path=str(path),
                content="new content",
            )
            assert "Wrote" in result
            assert path.read_text() == "new content"


class TestToolFileGlob:
    """Glob tool."""

    @pytest.mark.asyncio
    async def test_glob_py_files(self) -> None:
        result = await tool_file_glob.call(pattern="*.py", root="agentsx")
        assert result == "" or "agentsx" in result


# ── Built-in: ALL_TOOLS ──────────────────────────────────────────────


class TestAllTools:
    """The ALL_TOOLS constant contains all built-in tools."""

    def test_all_tools_count(self) -> None:
        assert len(ALL_TOOLS) >= 7

    def test_all_are_toolspecs(self) -> None:
        for t in ALL_TOOLS:
            assert isinstance(t, ToolSpec), f"{t.name} is not a ToolSpec"

    def test_no_duplicate_names(self) -> None:
        names = [t.name for t in ALL_TOOLS]
        assert len(names) == len(set(names)), f"Duplicate names: {names}"
