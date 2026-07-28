"""Extension system — observer + interceptor pattern.

Extensions observe and record; interceptors may suppress or modify.
"""

from agentsx.extensions.api import (
    ALL_EVENTS,
    ALL_INTERCEPTOR_EVENTS,
    EVENT_ON_ERROR,
    EVENT_ON_LOOP_END,
    EVENT_ON_LOOP_START,
    EVENT_ON_MODEL_REQUEST,
    EVENT_ON_MODEL_RESPONSE,
    EVENT_ON_TOOL_CALL,
    EVENT_ON_TOOL_RESULT,
    EVENT_POST_TOOL_CALL,
    EVENT_PRE_COMPACT,
    EVENT_PRE_TOOL_CALL,
    EVENT_SESSION_END,
    EVENT_SESSION_START,
    ExtensionAPI,
    ExtensionEvent,
    Handler,
    InterceptorEvent,
)
from agentsx.extensions.discovery import discover_extensions

__all__ = [
    "ALL_EVENTS",
    "ALL_INTERCEPTOR_EVENTS",
    "EVENT_ON_ERROR",
    "EVENT_ON_LOOP_END",
    "EVENT_ON_LOOP_START",
    "EVENT_ON_MODEL_REQUEST",
    "EVENT_ON_MODEL_RESPONSE",
    "EVENT_ON_TOOL_CALL",
    "EVENT_ON_TOOL_RESULT",
    "EVENT_POST_TOOL_CALL",
    "EVENT_PRE_COMPACT",
    "EVENT_PRE_TOOL_CALL",
    "EVENT_SESSION_END",
    "EVENT_SESSION_START",
    "ExtensionAPI",
    "ExtensionEvent",
    "Handler",
    "InterceptorEvent",
    "discover_extensions",
]
