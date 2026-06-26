"""Typed exception hierarchy for AgentsX.

All custom exceptions inherit from ``AgentsXError``.
"""

from __future__ import annotations


class AgentsXError(Exception):
    """Base exception for all AgentsX errors."""


class ProviderError(AgentsXError):
    """LLM provider communication error (authentication, rate limit, etc.)."""


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
