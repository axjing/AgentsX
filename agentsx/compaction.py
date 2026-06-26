"""Backward-compat alias. Import from agentsx.context instead."""

from __future__ import annotations

import warnings

from agentsx.context.compaction import (
    compact_messages,
    estimate_message_tokens,
    estimate_tokens,
    should_compact,
)

warnings.warn(
    "agentsx.compaction is deprecated; use agentsx.context",
    DeprecationWarning,
    stacklevel=2,
)
__all__ = [
    "compact_messages",
    "estimate_message_tokens",
    "estimate_tokens",
    "should_compact",
]
