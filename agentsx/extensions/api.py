"""Lightweight extension API — observer-only, no behaviour modification.

Design constraints (avoids the Hermes 8-hook plugin trap):
    - Extensions observe and record only; they never modify behaviour.
    - If you need to modify behaviour, write a Tool instead.
    - Exceptions in extension handlers are caught and logged (never crash the loop).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

try:
    from importlib.metadata import entry_points as _entry_points
except ImportError:  # pragma: no cover
    _entry_points = None  # type: ignore[assignment]

# ── Predefined event types ────────────────────────────────

EVENT_ON_LOOP_START = "on_loop_start"
"""Agent loop iteration begins."""

EVENT_ON_LOOP_END = "on_loop_end"
"""Agent loop iteration ends (normal or error)."""

EVENT_ON_MODEL_REQUEST = "on_model_request"
"""About to call the LLM provider."""

EVENT_ON_MODEL_RESPONSE = "on_model_response"
"""Received a response (delta or final) from the LLM."""

EVENT_ON_TOOL_CALL = "on_tool_call"
"""Tool call requested by the LLM (before execution)."""

EVENT_ON_TOOL_RESULT = "on_tool_result"
"""Tool execution finished (success or error)."""

EVENT_ON_ERROR = "on_error"
"""Non-fatal error occurred in the loop."""

ALL_EVENTS = frozenset(
    {
        EVENT_ON_LOOP_START,
        EVENT_ON_LOOP_END,
        EVENT_ON_MODEL_REQUEST,
        EVENT_ON_MODEL_RESPONSE,
        EVENT_ON_TOOL_CALL,
        EVENT_ON_TOOL_RESULT,
        EVENT_ON_ERROR,
    }
)

# ── Types ─────────────────────────────────────────────────


@dataclass
class ExtensionEvent:
    """A single event fired to registered extension handlers."""

    type: str
    """Event type — one of the ``EVENT_ON_*`` constants."""

    data: dict[str, Any] = field(default_factory=dict)
    """Event payload. Schema depends on the event type."""


Handler = Callable[[ExtensionEvent], Awaitable[None]]
"""Signature for extension event handlers."""


# ── Extension API ─────────────────────────────────────────


class ExtensionAPI:
    """Register and emit extension events.

    Usage::

        api = ExtensionAPI()
        api.on(EVENT_ON_TOOL_RESULT, my_handler)

        await api.emit(ExtensionEvent(
            type=EVENT_ON_TOOL_RESULT,
            data={"tool": "read", "duration_ms": 42},
        ))
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}

    # ── Public API ─────────────────────────────────────────

    def on(self, event_type: str, handler: Handler) -> None:
        """Register a handler for an event type.

        Multiple handlers may be registered for the same event type;
        they are invoked in registration order.
        """
        self._handlers.setdefault(event_type, []).append(handler)

    async def emit(self, event: ExtensionEvent) -> None:
        """Fire an event to all registered handlers.

        Exceptions raised by handlers are caught and logged.
        They never propagate to the caller.
        """
        for handler in self._handlers.get(event.type, []):
            try:
                await handler(event)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Extension handler failed for event '%s'",
                    event.type,
                )

    def load_entry_points(self, group: str = "agentsx.extensions") -> None:
        """Discover and load extensions via Python entry points.

        Each entry point must point to a callable that accepts an
        ``ExtensionAPI`` instance::

            def setup_extension(api: ExtensionAPI) -> None:
                api.on(EVENT_ON_TOOL_RESULT, my_handler)

        The callable is invoked immediately with ``self`` as argument.
        """
        if _entry_points is None:
            logger.warning("importlib.metadata not available; skipping extensions")
            return
        try:
            for ep in _entry_points(group=group):
                try:
                    setup = ep.load()
                    if callable(setup):
                        setup(self)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Failed to load extension '%s'",
                        ep.name,
                    )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to enumerate extension entry points")
