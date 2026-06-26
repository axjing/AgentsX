"""Lightweight retry utilities for provider and I/O operations.

Provides a simple, non-invasive retry wrapper that can be applied
to any async function. Uses exponential backoff with jitter.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def retry_async(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator for retrying async functions with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts.
        base_delay: Base delay in seconds for backoff calculation.
        max_delay: Maximum delay cap in seconds.
        retryable_exceptions: Tuple of exception types that trigger retry.
    """

    def decorator(
        fn: Callable[..., Awaitable[T]],
    ) -> Callable[..., Awaitable[T]]:
        @wraps(fn)
        async def wrapper(*args: object, **kwargs: object) -> T:
            last_exc: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return await fn(*args, **kwargs)
                except retryable_exceptions as exc:
                    last_exc = exc
                    if attempt >= max_retries:
                        raise
                    delay = min(base_delay * (2**attempt), max_delay)
                    jitter = delay * 0.5 * random.random()
                    logger.warning(
                        "%s failed (attempt %d/%d), retrying in %.1fs: %s",
                        fn.__name__,
                        attempt + 1,
                        max_retries,
                        delay + jitter,
                        exc,
                    )
                    await asyncio.sleep(delay + jitter)
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator
