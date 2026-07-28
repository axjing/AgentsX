"""Extension API — observer + interceptor pattern.

Design constraints:
    - Observer events: handlers observe and record only; they never modify behaviour.
    - Interceptor events: handlers can suppress or modify execution flow.
    - Exceptions in extension handlers are caught and logged (never crash the loop).
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

try:
    from importlib.metadata import entry_points as _entry_points
except ImportError:  # pragma: no cover
    _entry_points = None  # type: ignore[assignment]

# ── Observer event types (existing) ───────────────────────

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

# ── Interceptor event types (new) ────────────────────────

EVENT_PRE_TOOL_CALL = "pre_tool_call"
"""Before tool execution — handlers may suppress or modify args."""

EVENT_POST_TOOL_CALL = "post_tool_call"
"""After tool execution — handlers may modify the result."""

EVENT_PRE_COMPACT = "pre_compact"
"""Before context compaction — handlers may inspect/skip."""

EVENT_SESSION_START = "session_start"
"""Session created or loaded."""

EVENT_SESSION_END = "session_end"
"""Session about to be closed."""

ALL_EVENTS = frozenset(
    {
        EVENT_ON_LOOP_START,
        EVENT_ON_LOOP_END,
        EVENT_ON_MODEL_REQUEST,
        EVENT_ON_MODEL_RESPONSE,
        EVENT_ON_TOOL_CALL,
        EVENT_ON_TOOL_RESULT,
        EVENT_ON_ERROR,
        EVENT_PRE_TOOL_CALL,
        EVENT_POST_TOOL_CALL,
        EVENT_PRE_COMPACT,
        EVENT_SESSION_START,
        EVENT_SESSION_END,
    }
)

ALL_INTERCEPTOR_EVENTS = frozenset(
    {
        EVENT_PRE_TOOL_CALL,
        EVENT_POST_TOOL_CALL,
        EVENT_PRE_COMPACT,
        EVENT_SESSION_START,
        EVENT_SESSION_END,
    }
)

# ── Types ─────────────────────────────────────────────────


@dataclass
class ExtensionEvent:
    """A single event fired to registered extension handlers."""

    type: str
    """Event type — one of the ``EVENT_ON_*`` or ``EVENT_PRE_*`` constants."""

    data: dict[str, Any] = field(default_factory=dict)
    """Event payload. Schema depends on the event type."""


@dataclass
class InterceptorEvent(ExtensionEvent):
    """An event that handlers may suppress or modify.

    Interceptors run before the default behaviour.  A handler may call
    ``suppress()`` to prevent the default action entirely, or ``modify()``
    to alter the event data before the default action reads it.
    """

    _suppressed: bool = field(default=False, init=False, repr=False)
    _modified: bool = field(default=False, init=False, repr=False)

    def suppress(self) -> None:
        """Prevent the default action and subsequent handlers from running."""
        self._suppressed = True

    def modify(self, data: dict[str, Any]) -> None:
        """Merge *data* into the event payload."""
        self.data.update(data)
        self._modified = True

    @property
    def is_suppressed(self) -> bool:
        """Whether ``suppress()`` has been called."""
        return self._suppressed

    @property
    def is_modified(self) -> bool:
        """Whether ``modify()`` has been called."""
        return self._modified


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
        """Fire an observer event to all registered handlers.

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

    async def emit_interceptor(self, event: InterceptorEvent) -> InterceptorEvent:
        """Fire an interceptor event to all registered handlers.

        Unlike ``emit()``, this returns the event so the caller can
        inspect ``is_suppressed`` and ``is_modified``.
        Handlers are invoked in registration order.  If any handler calls
        ``suppress()``, subsequent handlers still run (for logging/audit
        purposes) but the caller must check ``is_suppressed`` afterwards.
        """
        for handler in self._handlers.get(event.type, []):
            try:
                await handler(event)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Interceptor handler failed for event '%s'",
                    event.type,
                )
        return event

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

    def load_extensions(
        self,
        *,
        include_entry_points: bool = True,
        include_user: bool = True,
        include_project: bool = True,
        include_builtin: bool = True,
    ) -> None:
        """Discover and load extensions from all enabled sources.

        Uses multi-source discovery (entry points, user dir, project dir,
        built-in).  Each source provides a ``setup(api)`` callable.
        """
        from agentsx.extensions.discovery import discover_extensions

        extensions = discover_extensions(
            include_entry_points=include_entry_points,
            include_user=include_user,
            include_project=include_project,
            include_builtin=include_builtin,
        )
        for name, setup_fn in extensions.items():
            try:
                setup_fn(self)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to setup extension '%s'", name)
