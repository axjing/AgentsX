"""Core data types for AgentsX.

All messages, tool calls, events, and security decisions are defined here.
Provider-agnostic — no module should import provider-specific types.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

# ── Message Role ──────────────────────────────────────────────


class MessageRole(str, Enum):
    """Role of a message in the conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


# ── Tool Types ────────────────────────────────────────────────


@dataclass
class ToolCall:
    """A tool call requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """Result of executing a tool call."""

    id: str
    tool_call_id: str
    content: str
    is_error: bool = False


# ── Message ───────────────────────────────────────────────────


@dataclass
class AgentMessage:
    """Internal message representation, independent of LLM provider.

    All messages in the agent loop use this type. Conversion to
    provider-specific format happens at the I/O boundary via
    ``convert_to_provider()``.
    """

    role: MessageRole
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    """Correlates a tool-result message to the tool call that produced it."""
    name: str | None = None
    id: str = field(default_factory=lambda: uuid4().hex[:12])

    def convert_to_provider(self, provider_type: str) -> dict[str, Any]:
        """Convert this message to provider-native format.

        Args:
            provider_type: ``"openai"`` or ``"anthropic"``.

        Returns:
            A dict in the provider's message format.
        """
        if provider_type == "openai":
            return self._to_openai()
        if provider_type == "anthropic":
            return self._to_anthropic()
        msg = f"Unknown provider type: {provider_type}"
        raise ValueError(msg)

    def _to_openai(self) -> dict[str, Any]:
        if self.role == MessageRole.TOOL:
            return {
                "role": "tool",
                "content": self.content,
                "tool_call_id": self.tool_call_id or "",
            }
        msg: dict[str, Any] = {"role": self.role.value, "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in self.tool_calls
            ]
        if self.name:
            msg["name"] = self.name
        return msg

    def _to_anthropic(self) -> dict[str, Any]:
        if self.role == MessageRole.TOOL:
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": self.tool_call_id or "",
                        "content": self.content,
                    }
                ],
            }
        msg: dict[str, Any] = {"role": self.role.value, "content": self.content}
        if self.tool_calls:
            msg["content"] = [
                {"type": "text", "text": self.content},
                *[
                    {
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    }
                    for tc in self.tool_calls
                ],
            ]
        return msg


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
    compacted_count: int
    preserved_count: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PromptEvent:
    tool_call: ToolCall
    policy_decision: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ErrorEvent:
    """Emitted on non-fatal errors during the agent loop."""

    error: Exception
    context: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


AgentEvent = (
    ModelRequestEvent
    | ModelResponseEvent
    | ToolExecutionEvent
    | ErrorEvent
    | CompactionEvent
    | PromptEvent
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


# ── Security ──────────────────────────────────────────────────


class Decision(str, Enum):
    """Security decision for a tool call.

    Inspired by Codex three-tier model.
    """

    ALLOW = "allow"
    PROMPT = "prompt"
    FORBIDDEN = "forbidden"
