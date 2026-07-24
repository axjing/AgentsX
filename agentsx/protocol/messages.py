"""Domain messages and value types for AgentsX.

AgentMessage, ToolCall, ContentPart, ToolResult, Decision, and
provider message converters.  These are the universal data types
shared across the agent loop, providers, tools, sessions, and
security layers.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

# Re-exported from converters module so existing code continues to work.
# Import lazily to avoid circular import (converters imports from events/messages).

__all__ = [
    "AgentMessage",
    "ContentPart",
    "ContentType",
    "Decision",
    "MessageRole",
    "ToolCall",
    "ToolResult",
    "ToolResultStatus",
]


# --- Multimodal Content Types ---


class ContentType(str, Enum):
    """Type of content part in a multimodal message."""

    TEXT = "text"
    IMAGE_URL = "image_url"
    IMAGE_BASE64 = "image_base64"
    AUDIO_URL = "audio_url"
    AUDIO_BASE64 = "audio_base64"
    VIDEO_URL = "video_url"
    VIDEO_BASE64 = "video_base64"


@dataclass
class ContentPart:
    """A single content part in a multimodal message."""

    type: ContentType
    text: str = ""
    image_url: str = ""
    audio_url: str = ""
    video_url: str = ""
    media_type: str = ""
    detail: str = "auto"

    @classmethod
    def make_text(cls, content: str) -> "ContentPart":
        return cls(type=ContentType.TEXT, text=content)

    @classmethod
    def make_image_url(cls, url: str, detail: str = "auto") -> "ContentPart":
        return cls(type=ContentType.IMAGE_URL, image_url=url, detail=detail)

    @classmethod
    def make_image_file(cls, path: str, detail: str = "auto") -> "ContentPart":
        import base64

        file_path = Path(path)
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

    @classmethod
    def make_audio_url(cls, url: str) -> "ContentPart":
        """Create an audio URL content part."""
        return cls(type=ContentType.AUDIO_URL, audio_url=url)

    @classmethod
    def make_audio_file(cls, path: str) -> "ContentPart":
        """Create an audio content part from a local file (base64)."""
        import base64

        file_path = Path(path)
        data = file_path.read_bytes()
        encoded = base64.b64encode(data).decode("ascii")
        ext = file_path.suffix.lower()
        audio_map = {
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".ogg": "audio/ogg",
            ".flac": "audio/flac",
            ".m4a": "audio/mp4",
            ".webm": "audio/webm",
        }
        media_type = audio_map.get(ext, "application/octet-stream")
        return cls(
            type=ContentType.AUDIO_BASE64,
            audio_url=f"data:{media_type};base64,{encoded}",
            media_type=media_type,
        )

    @classmethod
    def make_video_url(cls, url: str) -> "ContentPart":
        """Create a video URL content part."""
        return cls(type=ContentType.VIDEO_URL, video_url=url)

    @classmethod
    def make_video_file(cls, path: str) -> "ContentPart":
        """Create a video content part from a local file (base64)."""
        import base64

        file_path = Path(path)
        data = file_path.read_bytes()
        encoded = base64.b64encode(data).decode("ascii")
        ext = file_path.suffix.lower()
        video_map = {
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".mov": "video/quicktime",
            ".avi": "video/x-msvideo",
            ".mkv": "video/x-matroska",
        }
        media_type = video_map.get(ext, "application/octet-stream")
        return cls(
            type=ContentType.VIDEO_BASE64,
            video_url=f"data:{media_type};base64,{encoded}",
            media_type=media_type,
        )


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


# ── Tool Result ───────────────────────────────────────────────


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
        """Convert this message to provider-native format."""
        from agentsx.provider.converters import convert_to_provider  # noqa: PLC0415

        return convert_to_provider(self, provider_type)

    def _to_openai(self) -> dict[str, Any]:
        """Convert to OpenAI format."""
        from agentsx.provider.converters import message_to_openai  # noqa: PLC0415

        return message_to_openai(self)

    def _to_anthropic(self) -> dict[str, Any]:
        """Convert to Anthropic format."""
        from agentsx.provider.converters import message_to_anthropic  # noqa: PLC0415

        return message_to_anthropic(self)


# ── Security ──────────────────────────────────────────────────


class Decision(str, Enum):
    """Security decision for a tool call.

    Inspired by Codex three-tier model.
    """

    ALLOW = "allow"
    PROMPT = "prompt"
    FORBIDDEN = "forbidden"
