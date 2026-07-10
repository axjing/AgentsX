"""Tests for the structured ToolResult dataclass."""

from agentsx.core.tool_result import ToolResult, ToolResultStatus


def test_tool_result_status_enum_values() -> None:
    """ToolResultStatus has the expected values and str mixin."""
    assert ToolResultStatus.SUCCESS.value == "success"
    assert ToolResultStatus.ERROR.value == "error"
    assert ToolResultStatus.BLOCKED.value == "blocked"
    assert isinstance(ToolResultStatus.SUCCESS, str)


def test_tool_result_success_properties() -> None:
    """A SUCCESS result has correct property values."""
    result = ToolResult(
        tool_call_id="tc_1",
        status=ToolResultStatus.SUCCESS,
        content="hello world",
    )
    assert result.is_success is True
    assert result.is_error is False
    assert result.is_blocked is False
    assert result.error_detail is None
    assert result.to_legacy_string() == "hello world"


def test_tool_result_error_properties() -> None:
    """An ERROR result exposes the exception and error detail."""
    exc = ValueError("bad input")
    result = ToolResult(
        tool_call_id="tc_2",
        status=ToolResultStatus.ERROR,
        content="bad input",
        error=exc,
    )
    assert result.is_error is True
    assert result.is_success is False
    assert result.is_blocked is False
    assert result.error is exc
    assert result.error_detail == "bad input"
    assert result.to_legacy_string() == "bad input"


def test_tool_result_blocked_properties() -> None:
    """A BLOCKED result returns content as error detail."""
    result = ToolResult(
        tool_call_id="tc_3",
        status=ToolResultStatus.BLOCKED,
        content="Blocked by policy: 'exec' is forbidden",
    )
    assert result.is_blocked is True
    assert result.is_error is False
    assert result.is_success is False
    assert result.error_detail == "Blocked by policy: 'exec' is forbidden"
    assert result.to_legacy_string() == "Blocked by policy: 'exec' is forbidden"


def test_tool_result_metadata() -> None:
    """Metadata dictionary is mutable-safe and defaults to empty."""
    result = ToolResult(
        tool_call_id="tc_4",
        status=ToolResultStatus.SUCCESS,
        content="ok",
        metadata={"truncated": "true", "duration_ms": "42"},
    )
    assert result.metadata == {"truncated": "true", "duration_ms": "42"}

    # Default metadata is an independent empty dict
    result2 = ToolResult(
        tool_call_id="tc_5",
        status=ToolResultStatus.SUCCESS,
        content="ok",
    )
    assert result2.metadata == {}
    result2.metadata["key"] = "val"
    assert result.metadata.get("key") is None


def test_tool_result_repr() -> None:
    """Repr truncates content at 60 chars."""
    result = ToolResult(
        tool_call_id="tc_6",
        status=ToolResultStatus.SUCCESS,
        content="short",
    )
    assert "short" in repr(result)
    assert "tc_6" in repr(result)
    assert "success" in repr(result)

    long_content = "a" * 100
    result2 = ToolResult(
        tool_call_id="tc_7",
        status=ToolResultStatus.SUCCESS,
        content=long_content,
    )
    r = repr(result2)
    assert "..." in r
    assert len(r.split("content=")[1].rstrip(")")) < 70
