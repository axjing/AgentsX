"""Typed exception hierarchy for AgentsX.

All custom exceptions inherit from ``AgentsXError``.
"""


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
