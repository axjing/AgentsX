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

# --- Multimodal Content Types ---


class ContentType(str, Enum):
    """Type of content part in a multimodal message."""

    TEXT = "text"
    IMAGE_URL = "image_url"
    IMAGE_BASE64 = "image_base64"


@dataclass
class ContentPart:
    """A single content part in a multimodal message."""

    type: ContentType
    text: str = ""
    image_url: str = ""
    media_type: str = ""
    detail: str = "auto"

    @classmethod
    def make_text(cls, content: str) -> ContentPart:
        return cls(type=ContentType.TEXT, text=content)

    @classmethod
    def make_image_url(cls, url: str, detail: str = "auto") -> ContentPart:
        return cls(type=ContentType.IMAGE_URL, image_url=url, detail=detail)

    @classmethod
    def make_image_file(cls, path: str, detail: str = "auto") -> ContentPart:
        import base64
        from pathlib import Path as _Path

        file_path = _Path(path)
        data = file_path.read_bytes()
        encoded = base64.b64encode(data).decode("ascii")
        ext = file_path.suffix.lower()
        media_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        media_type = media_map.get(ext, "application/octet-stream")
        return cls(
            type=ContentType.IMAGE_BASE64,
            image_url=f"data:{media_type};base64,{encoded}",
            media_type=media_type,
            detail=detail,
        )


def _parse_image_source(data_url: str, media_type: str) -> dict[str, Any]:
    """Parse a data URL into Anthropic image source format."""
    if data_url.startswith("data:"):
        # Extract base64 data after the comma
        comma_idx = data_url.find(",")
        if comma_idx != -1:
            b64_data = data_url[comma_idx + 1 :]
            return {
                "type": "base64",
                "media_type": media_type,
                "data": b64_data,
            }
    return {
        "type": "base64",
        "media_type": media_type,
        "data": data_url,
    }


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
    content_parts: list[ContentPart] | None = None
    """Multimodal content parts. When set, takes precedence over *content*."""
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
        msg: dict[str, Any] = {"role": self.role.value}
        msg["content"] = self._build_content_parts("openai")
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

    def _build_content_parts(self, provider: str) -> str | list[dict[str, Any]]:
        """Build content for the given provider.

        Returns a string for text-only, or a list of content parts
        for multimodal messages.
        """
        if self.content_parts:
            parts: list[dict[str, Any]] = []
            for cp in self.content_parts:
                if cp.type == ContentType.TEXT:
                    parts.append({"type": "text", "text": cp.text})
                elif cp.type == ContentType.IMAGE_URL:
                    if provider == "openai":
                        parts.append(
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": cp.image_url,
                                    "detail": cp.detail,
                                },
                            }
                        )
                    elif provider == "anthropic":
                        parts.append(
                            {
                                "type": "image",
                                "source": _parse_image_source(
                                    cp.image_url, cp.media_type
                                ),
                            }
                        )
                elif cp.type == ContentType.IMAGE_BASE64:
                    if provider == "openai":
                        parts.append(
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": cp.image_url,
                                    "detail": cp.detail,
                                },
                            }
                        )
                    elif provider == "anthropic":
                        parts.append(
                            {
                                "type": "image",
                                "source": _parse_image_source(
                                    cp.image_url, cp.media_type
                                ),
                            }
                        )
            if parts and self.content:
                parts.insert(0, {"type": "text", "text": self.content})
            return parts if parts else self.content
        return self.content

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
        msg: dict[str, Any] = {"role": self.role.value}
        content_val = self._build_content_parts("anthropic")
        if isinstance(content_val, list):
            # Add tool_use blocks if present
            if self.tool_calls:
                content_val.extend(
                    [
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        }
                        for tc in self.tool_calls
                    ]
                )
            msg["content"] = content_val
        else:
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
            else:
                msg["content"] = content_val
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
