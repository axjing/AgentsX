"""Typed exception hierarchy for AgentsX and centralized error classification.

All custom exceptions inherit from ``AgentsXError``.  The error
classifier maps ``ProviderError`` instances to structured
``ClassifiedError`` objects with ``FailoverReason`` and
``RecoveryAction``, enabling intelligent recovery (auto-compaction,
retry, fallback) in the agent loop.
"""

from dataclasses import dataclass
from enum import Enum

# ── Exception hierarchy ──────────────────────────────────────


class AgentsXError(Exception):
    """Base exception for all AgentsX errors."""


class ProviderError(AgentsXError):
    """LLM provider communication error (authentication, rate limit, etc.)."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        """HTTP status code if this error came from an HTTP response."""

    @property
    def is_retryable(self) -> bool:
        """Check if this error represents a retryable condition.

        Retryable: 429 (rate limit), 5xx (server errors), network errors.
        Not retryable: 400 (bad request), 401 (auth error), 403 (forbidden).
        """
        if self.status_code is not None:
            return self.status_code in {429, 500, 502, 503, 504}
        # Fallback: check message for known patterns
        msg = str(self).lower()
        return any(
            token in msg for token in ["429", "500", "502", "503", "504", "rate limit"]
        )


class RetryExhaustedError(ProviderError):
    """Provider retries exhausted without success."""

    def __init__(self, message: str, last_error: Exception) -> None:
        super().__init__(message)
        self.last_error = last_error


class ToolError(AgentsXError):
    """Tool execution error (tool not found, execution failure, etc.)."""


class PolicyError(AgentsXError):
    """Security policy violation."""


class SessionError(AgentsXError):
    """Session storage error."""


# ── Error classification ─────────────────────────────────────


class FailoverReason(str, Enum):
    """Categorized reasons for provider failure."""

    THINKING_SIGNATURE = "thinking_signature"
    """Thinking block signature mismatch (Anthropic extended thinking)."""

    CONTEXT_OVERFLOW = "context_overflow"
    """Input exceeds the model's context window."""

    BILLING_EXHAUSTED = "billing_exhausted"
    """Account credits/quota exhausted (HTTP 402)."""

    AUTH_ERROR = "auth_error"
    """Authentication or authorization failure (HTTP 401/403)."""

    RATE_LIMIT = "rate_limit"
    """Request rate exceeded (HTTP 429 or similar)."""

    SERVER_ERROR = "server_error"
    """Provider-side server error (HTTP 5xx)."""

    NETWORK_ERROR = "network_error"
    """Network-level failure (timeout, connection refused, etc.)."""

    UNKNOWN = "unknown"
    """Unclassified error that may still be retryable."""


@dataclass
class RecoveryAction:
    """Recommended recovery actions for a classified error."""

    should_retry: bool = False
    """Whether the caller should retry the request."""

    should_compress: bool = False
    """Whether context compaction should be attempted before retry."""

    should_fallback: bool = False
    """Whether a fallback provider should be used."""

    delay_seconds: float = 0.0
    """Suggested backoff delay before retrying (seconds)."""

    user_hint: str = ""
    """Human-readable hint explaining the error to the user."""


@dataclass
class ClassifiedError:
    """A provider error annotated with classification and recovery info."""

    reason: FailoverReason
    """The categorized failure reason."""

    recovery: RecoveryAction
    """Recommended recovery actions."""

    original: Exception
    """The original provider error."""

    message: str
    """Human-readable error description."""


# Context-overflow markers to scan for in error messages.
_CONTEXT_OVERFLOW_MARKERS = [
    "context length",
    "maximum context",
    "token limit",
    "too many tokens",
    "prompt is too long",
    "input length",
]

# Network-heuristic tokens to scan for in error messages.
_NETWORK_MARKERS = [
    "connection",
    "timeout",
    "network",
    "ssl",
    "tls",
    "disconnect",
    "refused",
    "reset",
]


def _matches(text: str, markers: list[str]) -> bool:
    """Check if *text* contains any of the given *markers* (case-insensitive)."""
    lower = text.lower()
    return any(m in lower for m in markers)


def classify_api_error(err: Exception) -> ClassifiedError:
    """Classify a provider error into a structured ``ClassifiedError``.

    Applies a priority-ordered classification pipeline:

    1. Thinking signature mismatch
    2. Context overflow
    3. HTTP status codes
    4. Network heuristics
    5. Fallback to UNKNOWN

    Note:
        The parameter type is deliberately ``Exception`` rather than
        ``ProviderError`` so that callers can pass any exception (including
        raw network errors) without needing to wrap it first.

    Args:
        err: The exception to classify (typically a ``ProviderError``).

    Returns:
        A ``ClassifiedError`` with reason, recovery action, and message.
    """
    # Gather searchable text from the exception and its cause chain.
    message = str(err)
    cause = err.__cause__
    cause_text = str(cause) if cause is not None else ""
    combined = f"{message} {cause_text}".lower()

    status_code: int | None = getattr(err, "status_code", None)

    # 1. Thinking signature mismatch.
    if "thinking" in combined and (
        "signature" in combined or "not allowed" in combined
    ):
        return ClassifiedError(
            reason=FailoverReason.THINKING_SIGNATURE,
            recovery=RecoveryAction(
                should_retry=False,
                should_compress=False,
                should_fallback=True,
                delay_seconds=0.0,
                user_hint=(
                    "Thinking signature mismatch. The model rejected the "
                    "extended thinking block. Disable thinking or retry."
                ),
            ),
            original=err,
            message=message or "Thinking signature mismatch",
        )

    # 2. Context overflow.
    if _matches(combined, _CONTEXT_OVERFLOW_MARKERS):
        return ClassifiedError(
            reason=FailoverReason.CONTEXT_OVERFLOW,
            recovery=RecoveryAction(
                should_retry=True,
                should_compress=True,
                should_fallback=False,
                delay_seconds=0.0,
                user_hint=(
                    "Context window exceeded. Consider compacting the "
                    "conversation or using a model with a larger context."
                ),
            ),
            original=err,
            message=message or "Context overflow",
        )

    # 3. HTTP status code classification.
    if status_code is not None:
        if status_code == 401:
            return ClassifiedError(
                reason=FailoverReason.AUTH_ERROR,
                recovery=RecoveryAction(
                    should_retry=False,
                    should_compress=False,
                    should_fallback=True,
                    delay_seconds=0.0,
                    user_hint="Authentication failed. Check your API key.",
                ),
                original=err,
                message=message or "Authentication error",
            )

        if status_code == 402:
            # 402 with "try again" or "temporary" is likely rate-limited.
            if "try again" in combined or "temporary" in combined:
                return ClassifiedError(
                    reason=FailoverReason.RATE_LIMIT,
                    recovery=RecoveryAction(
                        should_retry=True,
                        should_compress=False,
                        should_fallback=False,
                        delay_seconds=5.0,
                        user_hint="Request temporarily blocked. Try again later.",
                    ),
                    original=err,
                    message=message or "Rate limited",
                )
            return ClassifiedError(
                reason=FailoverReason.BILLING_EXHAUSTED,
                recovery=RecoveryAction(
                    should_retry=False,
                    should_compress=False,
                    should_fallback=True,
                    delay_seconds=0.0,
                    user_hint="Account quota exhausted. Check your billing status.",
                ),
                original=err,
                message=message or "Billing quota exhausted",
            )

        if status_code == 429:
            return ClassifiedError(
                reason=FailoverReason.RATE_LIMIT,
                recovery=RecoveryAction(
                    should_retry=True,
                    should_compress=False,
                    should_fallback=False,
                    delay_seconds=5.0,
                    user_hint="Rate limit exceeded. Backing off before retry.",
                ),
                original=err,
                message=message or "Rate limit exceeded",
            )

        if status_code == 403:
            return ClassifiedError(
                reason=FailoverReason.AUTH_ERROR,
                recovery=RecoveryAction(
                    should_retry=False,
                    should_compress=False,
                    should_fallback=True,
                    delay_seconds=0.0,
                    user_hint="Access forbidden. Check permissions or API key.",
                ),
                original=err,
                message=message or "Forbidden",
            )

        if 500 <= status_code < 600:
            return ClassifiedError(
                reason=FailoverReason.SERVER_ERROR,
                recovery=RecoveryAction(
                    should_retry=True,
                    should_compress=False,
                    should_fallback=True,
                    delay_seconds=2.0,
                    user_hint="Provider server error. Retrying with backoff.",
                ),
                original=err,
                message=message or f"Server error ({status_code})",
            )

    # 4. Network heuristics.
    if _matches(combined, _NETWORK_MARKERS):
        return ClassifiedError(
            reason=FailoverReason.NETWORK_ERROR,
            recovery=RecoveryAction(
                should_retry=True,
                should_compress=False,
                should_fallback=False,
                delay_seconds=2.0,
                user_hint="Network error. Retrying with backoff.",
            ),
            original=err,
            message=message or "Network error",
        )

    # 5. Fallback: UNKNOWN (but retryable).
    return ClassifiedError(
        reason=FailoverReason.UNKNOWN,
        recovery=RecoveryAction(
            should_retry=True,
            should_compress=False,
            should_fallback=False,
            delay_seconds=1.0,
            user_hint="An unexpected error occurred. Retrying.",
        ),
        original=err,
        message=message or "Unknown error",
    )
