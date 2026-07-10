"""Structured tool result types.

Replaces plain-string tool results with a rich dataclass that carries
status enum, error detail, and optional metadata.
"""

from dataclasses import dataclass, field
from enum import Enum


class ToolResultStatus(str, Enum):
    """Status of a tool call execution."""

    SUCCESS = "success"
    ERROR = "error"
    BLOCKED = "blocked"


@dataclass
class ToolResult:
    """Structured result from a tool call execution.

    Attributes:
        tool_call_id: Correlation ID matching this result to its call.
        status: Execution outcome (SUCCESS, ERROR, or BLOCKED).
        content: Human-readable output text.
        error: The exception object, if an error occurred.
        metadata: Optional key-value metadata for downstream consumers.
    """

    tool_call_id: str
    status: ToolResultStatus
    content: str
    error: Exception | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        """Whether the tool call completed without error."""
        return self.status is ToolResultStatus.SUCCESS

    @property
    def is_error(self) -> bool:
        """Whether the tool call raised an exception."""
        return self.status is ToolResultStatus.ERROR

    @property
    def is_blocked(self) -> bool:
        """Whether the tool call was blocked by policy or guard."""
        return self.status is ToolResultStatus.BLOCKED

    @property
    def error_detail(self) -> str | None:
        """Return a human-readable error description, if any."""
        if self.error is not None:
            return str(self.error)
        if self.is_error or self.is_blocked:
            return self.content
        return None

    def to_legacy_string(self) -> str:
        """Return content for backward-compat string consumers.

        Returns:
            The content on success, or the error detail on error/blocked.
        """
        if self.is_success:
            return self.content
        return self.error_detail or ""

    def __repr__(self) -> str:
        truncated = (
            self.content[:60] + "..." if len(self.content) > 60 else self.content
        )
        return (
            f"ToolResult(tool_call_id={self.tool_call_id!r}, "
            f"status={self.status.value!r}, content={truncated!r})"
        )
