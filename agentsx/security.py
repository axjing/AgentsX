"""Backward-compat alias. Import from agentsx.security.policy instead."""

from __future__ import annotations

import warnings

from agentsx.security.policy import Decision, ExecutionPolicy, Rule

warnings.warn(
    "agentsx.security module is deprecated; use agentsx.security.policy",
    DeprecationWarning,
    stacklevel=2,
)
__all__ = ["Decision", "ExecutionPolicy", "Rule"]
