"""Backward-compat alias. Import from agentsx.session instead."""

import warnings

from agentsx.session.store import Session, SessionStore

warnings.warn(
    "agentsx.session module is deprecated; use agentsx.session.store",
    DeprecationWarning,
    stacklevel=2,
)
__all__ = ["Session", "SessionStore"]
