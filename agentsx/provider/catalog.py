"""Provider catalog loader and resolver.

Reads provider and model definitions from a TOML catalog, merges with
user overrides from ``~/.agentsx/catalog.toml``, and exposes a
``resolve_model()`` function for the factory.

Inspired by Tau's ``data/catalog.toml`` design: provider definitions
live in data, not code.  Adding a new model requires only editing a
TOML file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore[import-not-found, no-redef]

logger = logging.getLogger(__name__)

_CATALOG_DIR = Path(__file__).parent / "data"
_USER_CATALOG_PATH = Path.home() / ".agentsx" / "catalog.toml"


# ── Data model ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ModelEntry:
    """Per-model metadata in the catalog."""

    context_window: int = 0


@dataclass(frozen=True, slots=True)
class ProviderEntry:
    """One provider definition from catalog.toml."""

    name: str
    display_name: str = ""
    base_url: str = ""
    api_format: str = "openai"
    env_api_key: str = ""
    env_api_base: str = ""
    default_model: str = ""
    context_window: int = 0
    supports_vision: bool = False
    model_prefix: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)
    models: dict[str, ModelEntry] = field(default_factory=dict)


# ── Loading ────────────────────────────────────────────────────────────


def _parse_catalog(path: Path) -> dict:
    """Parse a TOML catalog file. Returns the raw dict."""
    return tomllib.loads(path.read_text(encoding="utf-8"))


@cache
def _load_builtin_catalog() -> dict[str, ProviderEntry]:
    """Load the built-in catalog from ``data/catalog.toml``.

    Cached after first call -- the file does not change at runtime.
    """
    raw = _parse_catalog(_CATALOG_DIR / "catalog.toml")
    return _entries_from_raw(raw.get("providers", []))


def _load_user_catalog() -> dict[str, ProviderEntry]:
    """Load user catalog overlay from ``~/.agentsx/catalog.toml``.

    Returns empty dict if the file does not exist or is invalid.
    """
    if not _USER_CATALOG_PATH.is_file():
        return {}
    try:
        raw = _parse_catalog(_USER_CATALOG_PATH)
        return _entries_from_raw(raw.get("providers", []))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        logger.warning("Failed to load user catalog: %s", exc)
        return {}


def _entries_from_raw(providers_raw: list[dict]) -> dict[str, ProviderEntry]:
    """Convert a list of raw TOML provider dicts to ``ProviderEntry`` objects."""
    entries: dict[str, ProviderEntry] = {}
    for p in providers_raw:
        models: dict[str, ModelEntry] = {}
        for m_name, m_data in (p.get("models", {}) or {}).items():
            models[m_name] = ModelEntry(
                context_window=int(m_data.get("context_window", 0)),
            )

        extra_headers: dict[str, str] = {}
        for k, v in (p.get("extra_headers", {}) or {}).items():
            extra_headers[k] = str(v)

        entries[p["name"]] = ProviderEntry(
            name=p["name"],
            display_name=p.get("display_name", p["name"]),
            base_url=p.get("base_url", ""),
            api_format=p.get("api_format", "openai"),
            env_api_key=p.get("env_api_key", ""),
            env_api_base=p.get("env_api_base", ""),
            default_model=p.get("default_model", ""),
            context_window=int(p.get("context_window", 0)),
            supports_vision=bool(p.get("supports_vision", False)),
            model_prefix=p.get("model_prefix", ""),
            extra_headers=extra_headers,
            models=models,
        )
    return entries


def _merge_catalogs(
    builtin: dict[str, ProviderEntry],
    user: dict[str, ProviderEntry],
) -> dict[str, ProviderEntry]:
    """Merge builtin and user catalogs.  User entries override builtin."""
    merged = dict(builtin)
    for name, user_entry in user.items():
        if name in merged:
            # Deep merge: user models override/extend builtin models
            base = merged[name]
            merged_models = dict(base.models)
            merged_models.update(user_entry.models)
            merged[name] = ProviderEntry(
                name=name,
                display_name=user_entry.display_name or base.display_name,
                base_url=user_entry.base_url or base.base_url,
                api_format=user_entry.api_format or base.api_format,
                env_api_key=user_entry.env_api_key or base.env_api_key,
                env_api_base=user_entry.env_api_base or base.env_api_base,
                default_model=user_entry.default_model or base.default_model,
                context_window=user_entry.context_window or base.context_window,
                supports_vision=user_entry.supports_vision or base.supports_vision,
                model_prefix=user_entry.model_prefix or base.model_prefix,
                extra_headers={**base.extra_headers, **user_entry.extra_headers},
                models=merged_models,
            )
        else:
            merged[name] = user_entry
    return merged


@cache
def load_merged_catalog() -> dict[str, ProviderEntry]:
    """Load and merge builtin + user catalogs.

    Cached for performance.  Call ``clear_catalog_cache()`` to force
    a reload after editing catalog files.
    """
    builtin = _load_builtin_catalog()
    user = _load_user_catalog()
    return _merge_catalogs(builtin, user)


def clear_catalog_cache() -> None:
    """Clear all catalog caches to force a reload from disk."""
    _load_builtin_catalog.cache_clear()
    load_merged_catalog.cache_clear()


# ── Resolution ─────────────────────────────────────────────────────────


def resolve_model(
    model_name: str,
    catalog: dict[str, ProviderEntry] | None = None,
) -> tuple[ProviderEntry, str] | None:
    """Resolve a model name to a (ProviderEntry, clean_model) pair.

    Resolution order:
        1. Slash notation: ``"qwen/qwen3.6-plus"`` → provider="qwen"
        2. Exact model lookup across all providers
        3. Prefix matching via ``model_prefix``

    Returns:
        ``(provider_entry, clean_model)`` or ``None`` if not found.
    """
    if catalog is None:
        catalog = load_merged_catalog()

    # 1. Slash notation
    if "/" in model_name:
        provider_hint = model_name.split("/")[0]
        clean_model = model_name.split("/", 1)[1]
        if provider_hint in catalog:
            entry = catalog[provider_hint]
            if entry.models and clean_model in entry.models:
                return entry, clean_model
            return entry, clean_model
        return None

    # 2. Exact model lookup
    for entry in catalog.values():
        if entry.models and model_name in entry.models:
            return entry, model_name

    # 3. Prefix matching
    for entry in catalog.values():
        if entry.model_prefix and model_name.startswith(entry.model_prefix):
            return entry, model_name

    # 4. Fallback: provider name starts with model name (e.g. "ollama" → "ollama/...")
    for entry in catalog.values():
        if entry.name and model_name.startswith(entry.name):
            return entry, model_name

    return None
