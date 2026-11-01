"""Tests for context tool_pruner module."""

from agentsx.context.tool_pruner import (
    _extract_tool_call_info,
    _summarize_bash,
    _summarize_create_skill,
    _summarize_edit,
    _summarize_glob,
    _summarize_grep,
    _summarize_mcp_call,
    _summarize_plan,
    _summarize_read,
    _summarize_remember,
    _summarize_spawn_agent,
    _summarize_web_fetch,
    _summarize_web_search,
    _summarize_write,
    prune_messages_for_compaction,
    prune_tool_output,
    summarize_tool_call,
)
from agentsx.protocol.messages import AgentMessage, MessageRole, ToolCall


class TestExtractToolCallInfo:
    """Tests for _extract_tool_call_info helper."""

    def test_no_tool_calls(self) -> None:
        msg = AgentMessage(role=MessageRole.USER, content="hello")
        assert _extract_tool_call_info(msg) == []

    def test_with_tool_calls(self) -> None:
        tc = ToolCall(id="call_123", name="test_tool", arguments={"key": "val"})
        msg = AgentMessage(role=MessageRole.ASSISTANT, content="", tool_calls=[tc])
        info = _extract_tool_call_info(msg)
        assert len(info) == 1
        assert info[0][0] == "call_123"
        assert info[0][1] == "test_tool"
        assert '"key": "val"' in info[0][2]


class TestToolSummarizers:
    """Tests for individual tool summarizer functions."""

    def test_summarize_bash_exit_code_and_lines(self) -> None:
        args: dict[str, object] = {"command": "git status"}
        content = "On branch main\nChanges to be committed:\nExit code: 0"
        summary = _summarize_bash(args, content)
        assert "[terminal] ran `git status` -> exit 0, 3 lines output" == summary

    def test_summarize_bash_json_exit_code(self) -> None:
        args: dict[str, object] = {"command": "ls -l"}
        content = '{"exit_code": 1}\nSome error'
        summary = _summarize_bash(args, content)
        assert "exit 1" in summary

    def test_summarize_bash_long_command_truncation(self) -> None:
        args: dict[str, object] = {"command": "a" * 100}
        summary = _summarize_bash(args, "ok")
        assert "..." in summary

    def test_summarize_read(self) -> None:
        args: dict[str, object] = {"path": "main.py"}
        summary = _summarize_read(args, "12345")
        assert summary == "[read] main.py (5 chars)"

    def test_summarize_write(self) -> None:
        args: dict[str, object] = {"path": "out.txt"}
        summary = _summarize_write(args, "line1\nline2\nline3")
        assert summary == "[write] out.txt (3 lines)"

    def test_summarize_edit(self) -> None:
        args: dict[str, object] = {"path": "app.py"}
        summary = _summarize_edit(args, "new edited content")
        assert "[edit] app.py (18 chars result)" == summary

    def test_summarize_grep_json_count(self) -> None:
        args: dict[str, object] = {"pattern": "def ", "path": "src"}
        content = '{"total_count": 42}'
        summary = _summarize_grep(args, content)
        assert summary == "[grep] 'def ' in src -> 42 matches"

    def test_summarize_grep_plain_lines(self) -> None:
        args: dict[str, object] = {"pattern": "TODO", "path": "."}
        content = "file1.py:10: TODO 1\nfile2.py:20: TODO 2"
        summary = _summarize_grep(args, content)
        assert summary == "[grep] 'TODO' in . -> 2 matches"

    def test_summarize_grep_no_matches(self) -> None:
        args: dict[str, object] = {"pattern": "MISSING", "path": "."}
        content = "No matches found."
        summary = _summarize_grep(args, content)
        assert summary == "[grep] 'MISSING' in . -> 0 matches"

    def test_summarize_glob(self) -> None:
        args: dict[str, object] = {"pattern": "*.py"}
        summary = _summarize_glob(args, "file1.py\nfile2.py")
        assert "[glob] '*.py' (17 chars)" == summary

    def test_summarize_web_fetch(self) -> None:
        args: dict[str, object] = {"url": "https://example.com"}
        summary = _summarize_web_fetch(args, "Sample webpage text")
        assert summary == "[web_fetch] https://example.com (19 chars)"

    def test_summarize_web_search(self) -> None:
        args: dict[str, object] = {"query": "python asyncio"}
        summary = _summarize_web_search(args, "Result 1\nResult 2")
        assert summary == "[web_search] 'python asyncio' (17 chars)"

    def test_summarize_spawn_agent(self) -> None:
        args: dict[str, object] = {
            "prompt": "Analyze code structure",
            "role": "leaf",
        }
        summary = _summarize_spawn_agent(args, "Full report")
        assert summary == (
            "[subagent:leaf] 'Analyze code structure' -> 11 chars output"
        )

    def test_summarize_plan(self) -> None:
        args: dict[str, object] = {"action": "add", "task": "Implement feature X"}
        summary = _summarize_plan(args, "Task added.")
        assert summary == "[plan] action=add 'Implement feature X'"

    def test_summarize_remember(self) -> None:
        args: dict[str, object] = {
            "content": "Always verify with pytest",
            "scope": "project",
        }
        summary = _summarize_remember(args, "Memory rule saved.")
        assert summary == "[remember:project] 'Always verify with pytest'"

    def test_summarize_mcp_call(self) -> None:
        args: dict[str, object] = {"server": "filesystem", "tool": "list_directory"}
        summary = _summarize_mcp_call(args, '["file1.txt", "file2.txt"]')
        assert summary == "[mcp:filesystem] list_directory -> 26 chars"

    def test_summarize_create_skill(self) -> None:
        args: dict[str, object] = {"name": "calc_tax"}
        summary = _summarize_create_skill(args, "Skill 'calc_tax' registered.")
        assert summary == "[skill:create] 'calc_tax' -> Skill 'calc_tax' registered."


class TestSummarizeToolCall:
    """Tests for summarize_tool_call dispatcher."""

    def test_known_tool(self) -> None:
        res = summarize_tool_call("tool_file_read", {"path": "test.txt"}, "data")
        assert "[read] test.txt (4 chars)" == res

    def test_unknown_tool_fallback(self) -> None:
        res = summarize_tool_call("custom_tool", {"arg1": "value1"}, "result text")
        assert "[custom_tool](arg1=value1) (11 chars)" == res


class TestPruneToolOutput:
    """Tests for prune_tool_output length limiter."""

    def test_under_threshold_unmodified(self) -> None:
        short_text = "This is short output."
        assert prune_tool_output(short_text, threshold=100) == short_text

    def test_over_threshold_truncated(self) -> None:
        long_text = "X" * 3000
        pruned = prune_tool_output(long_text, threshold=1000)
        assert len(pruned) < len(long_text)
        assert "chars omitted" in pruned


class TestPruneMessagesForCompaction:
    """Tests for prune_messages_for_compaction."""

    def test_messages_count_under_preserve_count(self) -> None:
        msgs = [
            AgentMessage(role=MessageRole.USER, content="Hello"),
            AgentMessage(role=MessageRole.ASSISTANT, content="Hi"),
        ]
        result = prune_messages_for_compaction(msgs, preserve_count=5)
        assert result == msgs

    def test_older_tool_messages_pruned_tail_preserved(self) -> None:
        tc = ToolCall(id="call_read", name="tool_file_read", arguments={"path": "a.py"})
        msgs = [
            AgentMessage(
                role=MessageRole.ASSISTANT,
                content="Reading file",
                tool_calls=[tc],
            ),
            AgentMessage(
                role=MessageRole.TOOL,
                content="line 1\nline 2\nline 3\nline 4\nline 5",
                tool_call_id="call_read",
            ),
            AgentMessage(role=MessageRole.USER, content="Next request"),
            AgentMessage(role=MessageRole.ASSISTANT, content="Done"),
        ]
        # Preserve only last 2 messages (USER + ASSISTANT)
        result = prune_messages_for_compaction(msgs, preserve_count=2)
        assert len(result) == 4
        # First tool call should be summarized
        assert result[1].role == MessageRole.TOOL
        assert "[read] a.py" in result[1].content
        # Tail messages should remain untouched
        assert result[2].content == "Next request"
        assert result[3].content == "Done"
