"""Resource limits for tool execution.

Prevents context window blowout and runaway execution.
Inspired by codex `tool_output_limits.py` and hermes-agent
`tool_result_storage.py`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ResourceLimits:
    """Configurable resource limits for tool execution."""

    max_output_chars: int = 50_000
    """Maximum characters returned by a single tool call."""

    max_stderr_chars: int = 5_000
    """Maximum stderr characters to include in error output."""

    max_file_read_lines: int = 10_000
    """Maximum lines returned by file read tools."""

    max_glob_results: int = 1_000
    """Maximum results returned by glob tool."""

    max_grep_matches: int = 500
    """Maximum matches returned by grep tool."""

    max_history_length: int = 10_000
    """Maximum shell command history entries."""

    def truncate_output(self, text: str, label: str = "output") -> str:
        """Truncate text to max_output_chars with a notice."""
        if len(text) <= self.max_output_chars:
            return text
        truncated = text[: self.max_output_chars]
        return (
            f"{truncated}\n... (output truncated at "
            f"{self.max_output_chars} chars, {len(text) - self.max_output_chars} "
            f"chars omitted)"
        )


# Module-level default limits
_default_limits = ResourceLimits()


def get_limits() -> ResourceLimits:
    """Return the default resource limits."""
    return _default_limits
