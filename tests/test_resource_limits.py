"""Tests for resource limits."""

from __future__ import annotations

from agentsx.security.resource_limits import ResourceLimits, get_limits


class TestResourceLimits:
    """ResourceLimits configuration and behavior."""

    def test_defaults(self) -> None:
        limits = ResourceLimits()
        assert limits.max_output_chars == 50_000
        assert limits.max_stderr_chars == 5_000
        assert limits.max_file_read_lines == 10_000
        assert limits.max_glob_results == 1_000
        assert limits.max_grep_matches == 500

    def test_truncate_under_limit(self) -> None:
        limits = ResourceLimits(max_output_chars=100)
        text = "short text"
        assert limits.truncate_output(text) == text

    def test_truncate_over_limit(self) -> None:
        limits = ResourceLimits(max_output_chars=10)
        text = "x" * 100
        result = limits.truncate_output(text)
        assert len(result) < len(text)
        assert "truncated" in result

    def test_truncate_preserves_prefix(self) -> None:
        limits = ResourceLimits(max_output_chars=5)
        text = "hello world"
        result = limits.truncate_output(text)
        assert result.startswith("hello")

    def test_get_limits_singleton(self) -> None:
        limits = get_limits()
        assert isinstance(limits, ResourceLimits)
        # Should return the same instance
        assert get_limits() is limits

    def test_custom_limits(self) -> None:
        limits = ResourceLimits(
            max_output_chars=1_000,
            max_grep_matches=100,
        )
        assert limits.max_output_chars == 1_000
        assert limits.max_grep_matches == 100
