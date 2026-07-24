"""Provider factory: create_provider() and _resolve_provider_kwargs().

Resolution order:
    1. Catalog lookup (data/catalog.toml + user overlay)
    2. Slash notation → provider hint → registry
    3. resolve_provider_name (alias/prefix from profile)
    4. Registered provider iteration
"""

import importlib

from agentsx.config import get_settings
from agentsx.protocol.errors import ProviderError
from agentsx.provider.abc import Model, Provider
from agentsx.provider.catalog import load_merged_catalog, resolve_model
from agentsx.provider.profile import (
    ProviderProfile,
    get_profile,
    register_profile,
    resolve_provider_name,
)
from agentsx.provider.registry import _PROVIDER_REGISTRY, register_provider

__all__ = ["create_provider", "register_provider"]


def _entry_to_profile(entry) -> ProviderProfile:
    """Convert a catalog ProviderEntry to a ProviderProfile."""
    from agentsx.provider.profile import ProviderProfile  # noqa: PLC0415

    return ProviderProfile(
        name=entry.name,
        display_name=entry.display_name,
        base_url=entry.base_url,
        api_format=entry.api_format,
        env_api_key=entry.env_api_key,
        env_api_base=entry.env_api_base,
        default_model=entry.default_model,
        context_window=entry.context_window,
        supports_vision=entry.supports_vision,
        model_prefix=entry.model_prefix,
        extra_headers=entry.extra_headers,
    )


def _resolve_provider_kwargs(
    provider_name: str,
    init_kwargs: dict[str, object],
) -> dict[str, object]:
    """Apply profile-aware api_key/api_base fallback for a provider."""
    settings = get_settings()
    profile = get_profile(provider_name)
    resolved = dict(init_kwargs)

    if not resolved.get("api_key"):
        if profile and profile.env_api_key:
            env_key = profile.env_api_key.removeprefix("AGENTSX_").lower()
            key_val = getattr(settings, env_key, "") or settings.api_key
            resolved["api_key"] = key_val
        else:
            key_attr = f"{provider_name}_api_key"
            resolved["api_key"] = getattr(settings, key_attr, "") or settings.api_key

    if not resolved.get("api_base"):
        if profile and profile.env_api_base:
            env_base = profile.env_api_base.removeprefix("AGENTSX_").lower()
            base_val = getattr(settings, env_base, "") or settings.api_base
            resolved["api_base"] = base_val or profile.base_url
        else:
            base_attr = f"{provider_name}_api_base"
            resolved["api_base"] = getattr(settings, base_attr, "") or settings.api_base

    return resolved


def create_provider(
    model_name: str,
    api_key: str | None = None,
    api_base: str | None = None,
    **kwargs: object,
) -> Provider:
    """Factory: create a Provider instance from a model name.

    Resolution order:
        1. Catalog lookup (data/catalog.toml + user overlay)
        2. Slash notation: ``"gemini/gemini-2.0-flash"`` → provider
        3. Model alias / prefix via :func:`resolve_provider_name`
        4. Iterate registered providers

    Args:
        model_name: Model identifier (e.g. ``"gpt-4o"``
            or ``"gemini/gemini-2.0-flash"``).
        api_key: API key for the provider.
        api_base: Optional custom API base URL.
        **kwargs: Additional provider-specific arguments.

    Returns:
        A configured Provider instance.

    Raises:
        ProviderError: If no provider is registered for the model.
    """
    for _mod in (
        "agentsx.provider.openai",
        "agentsx.provider.anthropic",
        "agentsx.provider.generic",
    ):
        try:
            importlib.import_module(_mod)
        except ImportError:
            pass

    if "/" in model_name:
        provider_hint = model_name.split("/")[0]
        clean_model = model_name.split("/", 1)[1]
    else:
        provider_hint = None
        clean_model = model_name

    init_kwargs: dict[str, object] = {}
    if api_key is not None:
        init_kwargs["api_key"] = api_key
    if api_base is not None:
        init_kwargs["api_base"] = api_base
    init_kwargs.update(kwargs)

    # ── 1. Catalog lookup (primary resolution path) ───────────────────
    catalog = load_merged_catalog()
    resolved = resolve_model(model_name, catalog)
    if resolved is not None:
        entry, resolved_model = resolved
        # Register profile from catalog if not already present
        if get_profile(entry.name) is None:
            register_profile(entry.name, _entry_to_profile(entry))

        profile = get_profile(entry.name)
        if entry.name in _PROVIDER_REGISTRY:
            resolved_kwargs = _resolve_provider_kwargs(entry.name, init_kwargs)
            return _PROVIDER_REGISTRY[entry.name](
                model=Model(id=resolved_model, provider_name=entry.name),
                **resolved_kwargs,
            )
        # Provider entry in catalog but not in registry → try GenericProvider
        if "generic" in _PROVIDER_REGISTRY:
            resolved_kwargs = _resolve_provider_kwargs(entry.name, init_kwargs)
            return _PROVIDER_REGISTRY["generic"](
                model=Model(id=resolved_model, provider_name=entry.name),
                **resolved_kwargs,
            )

    # ── 2. Slash notation → registry ──────────────────────────────────
    if provider_hint and provider_hint in _PROVIDER_REGISTRY:
        resolved_kwargs = _resolve_provider_kwargs(provider_hint, init_kwargs)
        return _PROVIDER_REGISTRY[provider_hint](
            model=Model(id=clean_model, provider_name=provider_hint),
            **resolved_kwargs,
        )

    # ── 3. resolve_provider_name (alias/prefix from profile) ──────────
    resolved_name = resolve_provider_name(model_name)
    if resolved_name and resolved_name in _PROVIDER_REGISTRY:
        resolved_kwargs = _resolve_provider_kwargs(resolved_name, init_kwargs)
        return _PROVIDER_REGISTRY[resolved_name](
            model=Model(id=clean_model, provider_name=resolved_name),
            **resolved_kwargs,
        )

    # ── 4. Iterate registered providers ───────────────────────────────
    for name, cls in _PROVIDER_REGISTRY.items():
        profile = get_profile(name)
        prefix = profile.model_prefix if profile else ""
        if prefix and model_name.startswith(prefix):
            resolved_kwargs = _resolve_provider_kwargs(name, init_kwargs)
            return cls(
                model=Model(id=clean_model, provider_name=name),
                **resolved_kwargs,
            )

    for name, cls in _PROVIDER_REGISTRY.items():
        if name and model_name.startswith(name):
            resolved_kwargs = _resolve_provider_kwargs(name, init_kwargs)
            return cls(
                model=Model(id=clean_model, provider_name=name),
                **resolved_kwargs,
            )

    msg = f"No provider registered for model: {model_name}"
    raise ProviderError(msg)
