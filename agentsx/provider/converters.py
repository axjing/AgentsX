"""Provider-specific message conversion functions.

Convert ``AgentMessage`` objects to OpenAI and Anthropic wire formats.
Used by the transport layer and the ``AgentMessage.convert_to_provider()``
method.
"""

import json
from typing import Any

from agentsx.protocol.messages import AgentMessage, ContentType, MessageRole

# Re-exported for consumers that need the helpers directly.
__all__ = [
    "message_to_openai",
    "message_to_anthropic",
    "convert_to_provider",
    "parse_image_source",
    "audio_format_from_url",
]


# ── Helpers ────────────────────────────────────────────────────


def parse_image_source(data_url: str, media_type: str) -> dict[str, Any]:
    """Parse a data URL into Anthropic image source format."""
    if data_url.startswith("data:"):
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


def audio_format_from_url(url: str, media_type: str) -> str:
    """Infer audio format from URL or media type."""
    format_map = {
        "audio/mpeg": "mp3",
        "audio/wav": "wav",
        "audio/ogg": "ogg",
        "audio/flac": "flac",
        "audio/mp4": "m4a",
        "audio/webm": "webm",
    }
    if media_type in format_map:
        return format_map[media_type]
    ext_map = {
        ".mp3": "mp3",
        ".wav": "wav",
        ".ogg": "ogg",
        ".flac": "flac",
        ".m4a": "m4a",
        ".webm": "webm",
    }
    for ext, fmt in ext_map.items():
        if ext in url.lower():
            return fmt
    return "mp3"


# ── Content building ──────────────────────────────────────────


def _build_content_parts(
    msg: AgentMessage,
    provider: str,
) -> str | list[dict[str, Any]]:
    """Build content for the given provider.

    Returns a string for text-only, or a list of content parts
    for multimodal messages.
    """
    if msg.content_parts:
        parts: list[dict[str, Any]] = []
        for cp in msg.content_parts:
            if cp.type == ContentType.TEXT:
                parts.append({"type": "text", "text": cp.text})
            elif cp.type in (ContentType.IMAGE_URL, ContentType.IMAGE_BASE64):
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
                            "source": parse_image_source(cp.image_url, cp.media_type),
                        }
                    )
        if parts and msg.content:
            parts.insert(0, {"type": "text", "text": msg.content})
        return parts if parts else msg.content
    return msg.content


# ── Provider conversion ───────────────────────────────────────


def message_to_openai(msg: AgentMessage) -> dict[str, Any]:
    """Convert an ``AgentMessage`` to OpenAI message format."""
    if msg.role == MessageRole.TOOL:
        return {
            "role": "tool",
            "content": msg.content,
            "tool_call_id": msg.tool_call_id or "",
        }
    result: dict[str, Any] = {"role": msg.role.value}
    result["content"] = _build_content_parts(msg, "openai")
    if msg.tool_calls:
        result["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments),
                },
            }
            for tc in msg.tool_calls
        ]
    if msg.name:
        result["name"] = msg.name
    return result


def message_to_anthropic(msg: AgentMessage) -> dict[str, Any]:
    """Convert an ``AgentMessage`` to Anthropic message format."""
    if msg.role == MessageRole.TOOL:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id or "",
                    "content": msg.content,
                }
            ],
        }
    result: dict[str, Any] = {"role": msg.role.value}
    content_val = _build_content_parts(msg, "anthropic")
    if isinstance(content_val, list):
        # Add tool_use blocks if present
        if msg.tool_calls:
            content_val.extend(
                [
                    {
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    }
                    for tc in msg.tool_calls
                ]
            )
        result["content"] = content_val
    else:
        if msg.tool_calls:
            result["content"] = [
                {"type": "text", "text": msg.content},
                *[
                    {
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    }
                    for tc in msg.tool_calls
                ],
            ]
        else:
            result["content"] = content_val
    return result


def convert_to_provider(msg: AgentMessage, provider: str) -> dict[str, Any]:
    """Convert a message to provider-native format.

    Args:
        msg: The ``AgentMessage`` to convert.
        provider: ``"openai"`` or ``"anthropic"``.

    Returns:
        A dict in the provider's message format.

    Raises:
        ValueError: If the provider type is unknown.
    """
    if provider == "openai":
        return message_to_openai(msg)
    if provider == "anthropic":
        return message_to_anthropic(msg)
    msg_text = f"Unknown provider type: {provider}"
    raise ValueError(msg_text)
