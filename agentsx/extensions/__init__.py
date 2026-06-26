"""Lightweight extension API -- observer-only, no behaviour modification.

Extensions observe and record; they never modify behaviour.
"""

from __future__ import annotations

from agentsx.extensions.api import (
    ALL_EVENTS,
    EVENT_ON_ERROR,
    EVENT_ON_LOOP_END,
    EVENT_ON_LOOP_START,
    EVENT_ON_MODEL_REQUEST,
    EVENT_ON_MODEL_RESPONSE,
    EVENT_ON_TOOL_CALL,
    EVENT_ON_TOOL_RESULT,
    ExtensionAPI,
    ExtensionEvent,
    Handler,
)

__all__ = [
    "ALL_EVENTS",
    "EVENT_ON_ERROR",
    "EVENT_ON_LOOP_END",
    "EVENT_ON_LOOP_START",
    "EVENT_ON_MODEL_REQUEST",
    "EVENT_ON_MODEL_RESPONSE",
    "EVENT_ON_TOOL_CALL",
    "EVENT_ON_TOOL_RESULT",
    "ExtensionAPI",
    "ExtensionEvent",
    "Handler",
]
