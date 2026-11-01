"""Watchdog — Loop and action thrashing detector.

Monitors the agent loop for repetitive actions, consecutive failures,
and deadlocks. When detected, emits warnings to break self-locking loops.
Inspired by dsh-superagent-prototype watchdog control loop.
"""

import json
from dataclasses import dataclass


@dataclass
class WatchdogWarning:
    """Warning produced by the watchdog when an anomaly is detected."""

    message: str
    kind: str
    tool_name: str
    count: int
    circuit_broken: bool = False


class Watchdog:
    """Monitors agent actions to detect loops and repeated errors."""

    def __init__(
        self,
        max_identical_calls: int = 3,
        max_consecutive_errors: int = 4,
        circuit_breaker_identical: int = 5,
        circuit_breaker_errors: int = 6,
    ) -> None:
        """Initialize the watchdog.

        Args:
            max_identical_calls: Number of consecutive identical tool calls
                before triggering a loop warning.
            max_consecutive_errors: Number of consecutive tool errors
                before triggering a failure warning.
            circuit_breaker_identical: Threshold to trip the circuit breaker
                for identical tool call thrashing.
            circuit_breaker_errors: Threshold to trip the circuit breaker
                for consecutive tool failures.
        """
        self._max_identical_calls = max_identical_calls
        self._max_consecutive_errors = max_consecutive_errors
        self._circuit_breaker_identical = circuit_breaker_identical
        self._circuit_breaker_errors = circuit_breaker_errors
        self._last_call_signature: tuple[str, str] | None = None
        self._identical_call_count: int = 0
        self._consecutive_error_count: int = 0

    def record_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, object],
        is_error: bool = False,
    ) -> WatchdogWarning | None:
        """Record a completed tool call and evaluate loop anomalies.

        Args:
            tool_name: Name of the executed tool.
            arguments: Arguments passed to the tool.
            is_error: Whether the tool execution resulted in an error.

        Returns:
            A WatchdogWarning if a loop or error anomaly is detected, else None.
        """
        try:
            serialized_args = json.dumps(arguments, sort_keys=True, default=str)
        except (TypeError, ValueError):
            serialized_args = str(arguments)

        signature = (tool_name, serialized_args)

        if signature == self._last_call_signature:
            self._identical_call_count += 1
        else:
            self._last_call_signature = signature
            self._identical_call_count = 1

        if is_error:
            self._consecutive_error_count += 1
        else:
            self._consecutive_error_count = 0

        # Check circuit breaker for thrashing (hard stop)
        if self._identical_call_count >= self._circuit_breaker_identical:
            count = self._identical_call_count
            return WatchdogWarning(
                message=(
                    f"Tool '{tool_name}' was called {count} times consecutively "
                    "with identical arguments without progress. "
                    "Circuit breaker tripped: execution stopped."
                ),
                kind="circuit_breaker_thrashing",
                tool_name=tool_name,
                count=count,
                circuit_broken=True,
            )

        # Check identical call thrashing (soft warning)
        if self._identical_call_count == self._max_identical_calls:
            count = self._identical_call_count
            return WatchdogWarning(
                message=(
                    f"Tool '{tool_name}' was called {count} times consecutively "
                    "with identical arguments without progress. "
                    "Re-evaluate your approach, inspect other files, or stop."
                ),
                kind="thrashing",
                tool_name=tool_name,
                count=count,
                circuit_broken=False,
            )

        # Check circuit breaker for errors (hard stop)
        if self._consecutive_error_count >= self._circuit_breaker_errors:
            count = self._consecutive_error_count
            return WatchdogWarning(
                message=(
                    f"Encountered {count} consecutive tool execution errors. "
                    "Circuit breaker tripped: execution stopped."
                ),
                kind="circuit_breaker_errors",
                tool_name=tool_name,
                count=count,
                circuit_broken=True,
            )

        # Check consecutive errors (soft warning)
        if self._consecutive_error_count == self._max_consecutive_errors:
            count = self._consecutive_error_count
            return WatchdogWarning(
                message=(
                    f"Encountered {count} consecutive tool execution errors. "
                    "Please analyze why previous tools failed and change your strategy."
                ),
                kind="consecutive_errors",
                tool_name=tool_name,
                count=count,
                circuit_broken=False,
            )

        return None

    def reset(self) -> None:
        """Reset internal tracking state."""
        self._last_call_signature = None
        self._identical_call_count = 0
        self._consecutive_error_count = 0
