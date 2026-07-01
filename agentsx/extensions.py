"""Backward-compat alias. Import from agentsx.extensions instead."""

import warnings

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

warnings.warn(
    "agentsx.extensions module is deprecated; use agentsx.extensions.api",
    DeprecationWarning,
    stacklevel=2,
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
