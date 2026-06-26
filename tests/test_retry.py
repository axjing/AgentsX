"""Tests for retry utilities."""

from __future__ import annotations

import pytest

from agentsx.provider.retry import retry_async


class TestRetryAsync:
    """retry_async decorator behaviour."""

    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(self) -> None:
        attempts: list[int] = []

        @retry_async(max_retries=3)
        async def succeed() -> str:
            attempts.append(1)
            return "ok"

        result = await succeed()
        assert result == "ok"
        assert len(attempts) == 1

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self) -> None:
        attempts: list[int] = []

        @retry_async(max_retries=3, base_delay=0.01)
        async def flaky() -> str:
            attempts.append(1)
            if len(attempts) < 3:
                raise ConnectionError("fail")
            return "ok"

        result = await flaky()
        assert result == "ok"
        assert len(attempts) == 3

    @pytest.mark.asyncio
    async def test_exhausts_retries(self) -> None:
        attempts: list[int] = []

        @retry_async(max_retries=2, base_delay=0.01)
        async def always_fail() -> str:
            attempts.append(1)
            raise ConnectionError("permanent fail")

        with pytest.raises(ConnectionError, match="permanent fail"):
            await always_fail()
        assert len(attempts) == 3  # 1 + 2 retries

    @pytest.mark.asyncio
    async def test_non_retryable_exception_not_retried(self) -> None:
        attempts: list[int] = []

        @retry_async(
            max_retries=3,
            base_delay=0.01,
            retryable_exceptions=(ConnectionError,),
        )
        async def value_error() -> str:
            attempts.append(1)
            raise ValueError("not retryable")

        with pytest.raises(ValueError, match="not retryable"):
            await value_error()
        assert len(attempts) == 1
