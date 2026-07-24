"""LLM Provider abstraction layer.

Each provider implements the ``Provider`` ABC with ``stream()`` and
``format_messages()``. The ``create_provider()`` factory selects the
right provider by model name.

Provider catalog (TOML):
    Provider and model definitions live in ``data/catalog.toml``.
    User overrides can be placed in ``~/.agentsx/catalog.toml``.
    Adding a new model requires only editing a TOML file.
"""

from agentsx.provider.abc import Model, Provider
from agentsx.provider.catalog import (
    ProviderEntry,
    clear_catalog_cache,
    load_merged_catalog,
    resolve_model,
)
from agentsx.provider.factory import _resolve_provider_kwargs, create_provider
from agentsx.provider.profile import ProviderProfile, get_profile, resolve_provider_name
from agentsx.provider.registry import _PROVIDER_REGISTRY, register_provider

__all__ = [
    "Model",
    "Provider",
    "ProviderEntry",
    "ProviderProfile",
    "_PROVIDER_REGISTRY",
    "_resolve_provider_kwargs",
    "clear_catalog_cache",
    "create_provider",
    "get_profile",
    "load_merged_catalog",
    "register_provider",
    "resolve_model",
    "resolve_provider_name",
]
