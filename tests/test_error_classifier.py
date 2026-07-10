"""Tests for the centralized API error classifier."""

from agentsx.core.error_classifier import (
    FailoverReason,
    classify_api_error,
)
from agentsx.core.errors import ProviderError


def test_classify_rate_limit_429() -> None:
    err = ProviderError("rate limit exceeded", status_code=429)
    result = classify_api_error(err)
    assert result.reason == FailoverReason.RATE_LIMIT
    assert result.recovery.should_retry is True
    assert result.recovery.should_compress is False
    assert result.recovery.should_fallback is False


def test_classify_auth_401() -> None:
    err = ProviderError("invalid api key", status_code=401)
    result = classify_api_error(err)
    assert result.reason == FailoverReason.AUTH_ERROR
    assert result.recovery.should_retry is False


def test_classify_context_overflow() -> None:
    err = ProviderError(
        "This model's maximum context length is 8192 tokens. "
        "However, you requested 12000 tokens.",
        status_code=400,
    )
    result = classify_api_error(err)
    assert result.reason == FailoverReason.CONTEXT_OVERFLOW
    assert result.recovery.should_compress is True
    assert result.recovery.should_retry is True


def test_classify_billing_402() -> None:
    err = ProviderError("insufficient funds", status_code=402)
    result = classify_api_error(err)
    assert result.reason == FailoverReason.BILLING_EXHAUSTED
    assert result.recovery.should_retry is False
    assert result.recovery.should_fallback is True


def test_classify_server_503_retryable() -> None:
    err = ProviderError("service unavailable", status_code=503)
    result = classify_api_error(err)
    assert result.reason == FailoverReason.SERVER_ERROR
    assert result.recovery.should_retry is True


def test_classify_unknown_retryable() -> None:
    """Unknown errors default to retryable for resilience."""
    err = ProviderError("something weird happened")
    result = classify_api_error(err)
    assert result.reason == FailoverReason.UNKNOWN
    assert result.recovery.should_retry is True


def test_classify_thinking_signature() -> None:
    """Detect Anthropic extended thinking signature mismatch."""
    err = ProviderError(
        "error: tools are not allowed while using thinking. "
        "thinking signature mismatch",
        status_code=400,
    )
    result = classify_api_error(err)
    assert result.reason == FailoverReason.THINKING_SIGNATURE
    assert result.recovery.should_retry is False


def test_classify_timeout_network() -> None:
    """Network/timeout errors should be classified as transient."""
    err = ProviderError("Connection error")
    err.__cause__ = ConnectionError("Connection refused")
    result = classify_api_error(err)
    assert result.recovery.should_retry is True
