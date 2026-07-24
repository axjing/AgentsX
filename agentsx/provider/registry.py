"""Provider registry: registration and lookup."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentsx.provider.abc import Provider

# ── Provider Registry ──────────────────────────────────────────────────

_PROVIDER_REGISTRY: dict[str, type[Provider]] = {}


def register_provider(name: str, provider_cls: type[Provider]) -> None:
    """Register a provider class for use by ``create_provider()``."""
    _PROVIDER_REGISTRY[name] = provider_cls
