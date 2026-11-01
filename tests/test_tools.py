"""Tests for tool system: ToolSpec, ToolRegistry, decorator, built-ins."""

import tempfile
from pathlib import Path

import pytest

from agentsx.tools import ToolRegistry, ToolSpec, tool
from agentsx.tools.builtin import ALL_TOOLS
from agentsx.tools.builtin.exec.shell import tool_bash
from agentsx.tools.builtin.read.filesystem import (
    tool_file_glob,
    tool_file_grep,
    tool_file_read,
)
from agentsx.tools.builtin.write.filesystem import (
    tool_file_edit,
    tool_file_write,
)

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
        func = openai_def["function"]
        assert func["name"] == "dummy"  # type: ignore[index]
        params = func["parameters"]  # type: ignore[index]
        assert "arg1" in params["properties"]

    @pytest.mark.asyncio
    async def test_call_sync(self) -> None:
        def add(a: int, b: int) -> int:
            return a + b

        spec = ToolSpec(name="add", description="Add two numbers", fn=add)
        result = await spec.call(a=1, b=2)
        assert result.content == "3"

    @pytest.mark.asyncio
    async def test_call_async(self) -> None:
        async def slow_add(a: int, b: int) -> int:
            return a + b

        spec = ToolSpec(name="sadd", description="Slow add", fn=slow_add)
        result = await spec.call(a=10, b=20)
        assert result.content == "30"

    @pytest.mark.asyncio
    async def test_call_returns_tool_result(self) -> None:
        def add(a: int, b: int) -> int:
            return a + b

        spec = ToolSpec(name="add2", description="Add two numbers", fn=add)
        result = await spec.call(a=5, b=7)
        assert result.is_success
        assert result.content == "12"

    @pytest.mark.asyncio
    async def test_call_error_returns_tool_result(self) -> None:
        def broken() -> str:
            msg = "internal"
            raise ValueError(msg)

        spec = ToolSpec(name="broken", description="Broken tool", fn=broken)
        result = await spec.call()
        assert result.is_error
        assert "internal" in result.content

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
        names = [t["function"]["name"] for t in tools]  # type: ignore[index]
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
        result = await registry.call("nope")
        assert result.is_error
        assert "Unknown tool" in result.content

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
        func = tools[0]["function"]
        assert func["name"] == "greet"  # type: ignore[index]


# ── Decorator ────────────────────────────────────────────────────────


class TestToolDecorator:
    """``@tool`` decorator behaviour."""

    def test_decorator_no_args(self) -> None:
        @tool()
        def hello(name: str) -> str:
            """Say hello."""
            return f"Hello, {name}!"

        assert isinstance(hello, ToolSpec)
        assert hello.name == "hello"
        assert hello.description == "Say hello."
        assert "name" in hello.parameters["properties"]  # type: ignore[operator]

    def test_decorator_with_name_override(self) -> None:
        @tool(name="custom_greet", description="Custom greeting")
        def greet() -> str:
            return "hi"

        assert greet.name == "custom_greet"
        assert greet.description == "Custom greeting"

    @pytest.mark.asyncio
    async def test_decorator_callable(self) -> None:
        @tool(description="Add numbers")
        def add(a: int, b: int) -> int:
            return a + b

        result = await add.call(a=3, b=4)
        assert result.is_success
        assert result.content == "7"

    def test_decorator_with_check_fn(self) -> None:
        @tool(description="Conditional tool", check_fn=lambda: False)
        def conditional() -> str:
            return "never"

        assert isinstance(conditional, ToolSpec)
        assert conditional.check_fn() is False


# ── Built-in Tools ───────────────────────────────────────────────────


class TestToolFileRead:
    """Read tool with real files."""

    @pytest.mark.asyncio
    async def test_read_existing(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("line1\nline2\nline3\n")
            tmp = f.name
        try:
            result = await tool_file_read.call(path=tmp)
            assert "line1" in result.content
            assert "line2" in result.content
            assert "line3" in result.content
        finally:
            Path(tmp).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_read_missing(self) -> None:
        result = await tool_file_read.call(path="/nonexistent/file.txt")
        assert "file not found" in result.content

    @pytest.mark.asyncio
    async def test_read_with_offset(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("a\nb\nc\nd\n")
            tmp = f.name
        try:
            result = await tool_file_read.call(path=tmp, offset=3)
            lines = result.content.strip().split("\n")
            assert lines[0].startswith("3: c")
        finally:
            Path(tmp).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_read_non_utf8_bytes(self, tmp_path: Path) -> None:
        target = tmp_path / "bad.txt"
        target.write_bytes(b"hello \xff\xfe world\n")
        result = await tool_file_read.call(path=str(target))
        assert not result.is_error
        assert "hello" in result.content
        assert "world" in result.content


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
            assert "Wrote" in result.content
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
            assert "Wrote" in result.content
            assert path.read_text() == "new content"


class TestToolFileEdit:
    """Edit tool with unified diff feedback."""

    @pytest.mark.asyncio
    async def test_edit_file_success(self, tmp_path: Path) -> None:
        target = tmp_path / "hello.py"
        target.write_text("def hello():\n    print('hi')\n")
        res = await tool_file_edit.call(
            path=str(target),
            old_string="print('hi')",
            new_string="print('hello world')",
        )
        assert not res.is_error
        assert "Edited" in res.content
        assert "```diff" in res.content
        assert "-    print('hi')" in res.content
        assert "+    print('hello world')" in res.content
        assert target.read_text() == "def hello():\n    print('hello world')\n"

    @pytest.mark.asyncio
    async def test_edit_file_not_found(self, tmp_path: Path) -> None:
        res = await tool_file_edit.call(
            path=str(tmp_path / "missing.py"),
            old_string="a",
            new_string="b",
        )
        assert "Error: file not found" in res.content

    @pytest.mark.asyncio
    async def test_edit_old_string_not_found(self, tmp_path: Path) -> None:
        target = tmp_path / "app.py"
        target.write_text("x = 1\n")
        res = await tool_file_edit.call(
            path=str(target),
            old_string="y = 2",
            new_string="y = 3",
        )
        assert "Error: old_string not found" in res.content

    @pytest.mark.asyncio
    async def test_edit_identical_string(self, tmp_path: Path) -> None:
        target = tmp_path / "app.py"
        target.write_text("x = 1\n")
        res = await tool_file_edit.call(
            path=str(target),
            old_string="x = 1",
            new_string="x = 1",
        )
        assert "identical" in res.content

    @pytest.mark.asyncio
    async def test_edit_file_crlf_self_healing(self, tmp_path: Path) -> None:
        target = tmp_path / "crlf.py"
        # File has Windows CRLF
        target.write_bytes(b"line 1\r\nline 2\r\nline 3\r\n")
        # LLM supplies Unix LF old_string and new_string
        res = await tool_file_edit.call(
            path=str(target),
            old_string="line 2\n",
            new_string="line 2 modified\n",
        )
        assert not res.is_error
        assert "Edited" in res.content
        assert b"line 1\r\nline 2 modified\r\nline 3\r\n" == target.read_bytes()

    @pytest.mark.asyncio
    async def test_edit_file_ambiguous_matches(self, tmp_path: Path) -> None:
        target = tmp_path / "ambiguous.py"
        target.write_text("val = 1\nval = 1\n")
        res = await tool_file_edit.call(
            path=str(target),
            old_string="val = 1",
            new_string="val = 2",
        )
        assert "matches 2 locations" in res.content

    @pytest.mark.asyncio
    async def test_edit_file_not_a_file(self, tmp_path: Path) -> None:
        sub_dir = tmp_path / "subdir"
        sub_dir.mkdir()
        res = await tool_file_edit.call(
            path=str(sub_dir),
            old_string="a",
            new_string="b",
        )
        assert "not a file" in res.content


class TestToolFileGlob:
    """Glob tool."""

    @pytest.mark.asyncio
    async def test_glob_py_files(self) -> None:
        result = await tool_file_glob.call(pattern="*.py", root="agentsx")
        assert result.content == "" or "agentsx" in result.content


class TestToolFileGrep:
    """Grep tool."""

    @pytest.mark.asyncio
    async def test_grep_basic_match(self, tmp_path: Path) -> None:
        (tmp_path / "code.py").write_text("def find_me():\n    pass\n")
        res = await tool_file_grep.call(pattern="find_me", root=str(tmp_path))
        assert not res.is_error
        assert "code.py:1:def find_me():" in res.content

    @pytest.mark.asyncio
    async def test_grep_skips_ignored_dirs(self, tmp_path: Path) -> None:
        venv_dir = tmp_path / ".venv" / "sub"
        venv_dir.mkdir(parents=True)
        (venv_dir / "hidden.py").write_text("TARGET_PHRASE\n")

        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True)
        (src_dir / "visible.py").write_text("TARGET_PHRASE\n")

        res = await tool_file_grep.call(pattern="TARGET_PHRASE", root=str(tmp_path))
        assert not res.is_error
        assert "visible.py" in res.content
        assert ".venv" not in res.content

    @pytest.mark.asyncio
    async def test_grep_not_a_directory(self, tmp_path: Path) -> None:
        file_path = tmp_path / "file.txt"
        file_path.write_text("content")
        res = await tool_file_grep.call(pattern="test", root=str(file_path))
        assert "Error: not a directory" in res.content

    @pytest.mark.asyncio
    async def test_grep_invalid_regex(self, tmp_path: Path) -> None:
        res = await tool_file_grep.call(pattern="[unclosed", root=str(tmp_path))
        assert "Error: invalid regex" in res.content


class TestToolBash:
    """Bash shell execution tool."""

    @pytest.mark.asyncio
    async def test_bash_echo(self) -> None:
        res = await tool_bash.call(command="python -c \"print('bash_success')\"")
        assert not res.is_error
        assert "bash_success" in res.content
        assert "Exit code: 0" in res.content

    @pytest.mark.asyncio
    async def test_bash_cwd_valid(self, tmp_path: Path) -> None:
        sub = tmp_path / "subfolder"
        sub.mkdir()
        (sub / "marker.txt").write_text("marker_present")
        cmd = "python -c \"import os; print(os.listdir('.'))\""
        res = await tool_bash.call(command=cmd, cwd=str(sub))
        assert not res.is_error
        assert "marker.txt" in res.content

    @pytest.mark.asyncio
    async def test_bash_cwd_invalid(self) -> None:
        res = await tool_bash.call(command="echo 1", cwd="/nonexistent_dir_12345")
        assert "Error: directory not found" in res.content


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
