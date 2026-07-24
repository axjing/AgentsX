"""Event types for the agent loop and provider streams."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from agentsx.protocol.messages import AgentMessage, ToolCall, ToolResult

__all__ = [
    "AgentEndEvent",
    "AgentEvent",
    "AgentStartEvent",
    "CompactionEvent",
    "ErrorEvent",
    "ModelRequestEvent",
    "ModelResponseEvent",
    "PromptEvent",
    "RetryEvent",
    "StreamEvent",
    "TextDeltaEvent",
    "TextStreamEvent",
    "ToolCallStreamEvent",
    "ToolExecutionEvent",
    "ToolExecutionStartEvent",
    "TurnEndEvent",
    "TurnStartEvent",
]


# ── Events ────────────────────────────────────────────────────


@dataclass
class ModelRequestEvent:
    """Emitted when the agent is about to call the LLM."""

    messages: list[AgentMessage]
    model: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ModelResponseEvent:
    """Emitted for each token received from the LLM."""

    content: str
    delta: bool = False
    """True for streaming tokens, False for the final assembled response."""

    step: int = 0
    """Step number in the agent loop (1-based)."""

    usage: dict[str, int] | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ToolExecutionEvent:
    """Emitted when a tool call execution completes."""

    tool_call: ToolCall
    result: ToolResult
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CompactionEvent:
    """Emitted when context compaction occurs."""

    compacted_count: int
    preserved_count: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PromptEvent:
    """Emitted when a tool call requires user approval."""

    tool_call: ToolCall
    policy_decision: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ErrorEvent:
    """Emitted on non-fatal errors during the agent loop."""

    error: Exception
    context: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AgentStartEvent:
    """Emitted when the agent loop begins."""

    model: str
    step: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AgentEndEvent:
    """Emitted when the agent loop completes."""

    step: int
    reason: str
    """``"completed"`` (no tool calls), ``"max_steps"``, or ``"error"``."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TurnStartEvent:
    """Emitted at the start of each agent turn."""

    turn: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TurnEndEvent:
    """Emitted at the end of each agent turn."""

    turn: int
    had_tool_calls: bool
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TextDeltaEvent:
    """A single text token from the model response."""

    text: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RetryEvent:
    """Emitted when a provider retry/backoff occurs."""

    attempt: int
    max_attempts: int
    reason: str
    delay: float
    """Seconds until next retry."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ToolExecutionStartEvent:
    """Emitted before a tool call is executed."""

    tool_name: str
    tool_call_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


AgentEvent = (
    AgentStartEvent
    | AgentEndEvent
    | TurnStartEvent
    | TurnEndEvent
    | ModelRequestEvent
    | TextDeltaEvent
    | ModelResponseEvent
    | ToolExecutionStartEvent
    | ToolExecutionEvent
    | ErrorEvent
    | CompactionEvent
    | PromptEvent
    | RetryEvent
)
"""Union type for all agent events. Consumers use ``isinstance()`` to dispatch."""

# ── Provider Stream Events ──────────────────────────────────


@dataclass
class TextStreamEvent:
    """A text token yielded from the provider stream."""

    text: str


@dataclass
class ToolCallStreamEvent:
    """A complete tool call detected in the provider stream."""

    tool_call: ToolCall


StreamEvent = TextStreamEvent | ToolCallStreamEvent
"""Items yielded by ``Provider.stream()`` — text tokens or complete tool calls."""
