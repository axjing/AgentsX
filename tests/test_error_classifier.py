"""Tests for the centralized API error classifier."""

from agentsx.protocol.errors import (
    FailoverReason,
    ProviderError,
    classify_api_error,
)


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
    assert result.reason == FailoverReason.NETWORK_ERROR
    assert result.recovery.should_retry is True


def test_classify_402_temporary_as_rate_limit() -> None:
    """402 with 'try again' or 'temporary' in message should be RATE_LIMIT."""
    err = ProviderError("Credit limit reached, try again later", status_code=402)
    result = classify_api_error(err)
    assert result.reason == FailoverReason.RATE_LIMIT
    assert result.recovery.should_retry is True
    assert result.recovery.should_fallback is False

    err2 = ProviderError("Temporary quota exceeded", status_code=402)
    result2 = classify_api_error(err2)
    assert result2.reason == FailoverReason.RATE_LIMIT


def test_classify_auth_403() -> None:
    """HTTP 403 should be AUTH_ERROR and not retryable."""
    err = ProviderError("Access denied", status_code=403)
    result = classify_api_error(err)
    assert result.reason == FailoverReason.AUTH_ERROR
    assert result.recovery.should_retry is False
    assert result.recovery.should_fallback is True


def test_classify_server_500_retryable() -> None:
    """HTTP 500 should be SERVER_ERROR and retryable."""
    err = ProviderError("Internal server error", status_code=500)
    result = classify_api_error(err)
    assert result.reason == FailoverReason.SERVER_ERROR
    assert result.recovery.should_retry is True
    assert result.recovery.should_fallback is True
