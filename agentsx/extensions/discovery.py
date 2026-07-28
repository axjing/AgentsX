"""Multi-source extension discovery.

Discovers extensions from four sources in priority order:
1. Python entry points (pip-installed packages)
2. User plugins (~/.agentsx/extensions/)
3. Project plugins (.agentsx/extensions/ in cwd)
4. Built-in plugins (agentsx/extensions/builtin/)

Each source provides a ``setup(api: ExtensionAPI)`` callable.
Sources are loaded in order; later sources can override earlier ones.
"""

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

try:
    from importlib.metadata import entry_points as _entry_points
except ImportError:  # pragma: no cover
    _entry_points = None  # type: ignore[assignment]


class ExtensionSetup(Protocol):
    """Callable that configures an ExtensionAPI instance."""

    def __call__(self, api: Any) -> None: ...


def _discover_entry_points(
    group: str = "agentsx.extensions",
) -> dict[str, ExtensionSetup]:
    """Discover extensions via Python entry points (pip packages)."""
    result: dict[str, ExtensionSetup] = {}
    if _entry_points is None:
        return result
    try:
        for ep in _entry_points(group=group):
            try:
                setup = ep.load()
                if callable(setup):
                    result[ep.name] = setup
            except Exception:  # noqa: BLE001
                logger.exception("Failed to load entry point '%s'", ep.name)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to enumerate entry points for '%s'", group)
    return result


def _discover_user_plugins() -> dict[str, ExtensionSetup]:
    """Discover extensions from ~/.agentsx/extensions/."""
    home = Path.home()
    plugin_dir = home / ".agentsx" / "extensions"
    return _discover_from_directory(plugin_dir, source="user")


def _discover_project_plugins() -> dict[str, ExtensionSetup]:
    """Discover extensions from .agentsx/extensions/ in the current directory."""
    plugin_dir = Path.cwd() / ".agentsx" / "extensions"
    return _discover_from_directory(plugin_dir, source="project")


def _discover_builtin_plugins() -> dict[str, ExtensionSetup]:
    """Discover built-in extensions from agentsx/extensions/builtin/."""
    builtin_dir = Path(__file__).parent / "builtin"
    return _discover_from_directory(builtin_dir, source="builtin")


def _discover_from_directory(
    directory: Path,
    source: str,
) -> dict[str, ExtensionSetup]:
    """Load extension setup functions from a directory.

    Each .py file in *directory* that defines a ``setup(api)`` function
    is treated as an extension.  The extension name is derived from the
    filename (without .py suffix).
    """
    result: dict[str, ExtensionSetup] = {}
    if not directory.is_dir():
        return result

    for py_file in sorted(directory.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        ext_name = f"{source}:{py_file.stem}"
        try:
            spec = importlib.util.spec_from_file_location(ext_name, py_file)
            if spec is None or spec.loader is None:
                logger.warning("Cannot load spec for '%s'", py_file)
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[ext_name] = module
            spec.loader.exec_module(module)
            setup_fn = getattr(module, "setup", None)
            if setup_fn is not None and callable(setup_fn):
                result[ext_name] = setup_fn
            else:
                logger.debug("No setup() in '%s'", py_file)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to load extension from '%s'", py_file)
    return result


def discover_extensions(
    *,
    group: str = "agentsx.extensions",
    include_entry_points: bool = True,
    include_user: bool = True,
    include_project: bool = True,
    include_builtin: bool = True,
) -> dict[str, ExtensionSetup]:
    """Discover extensions from all enabled sources.

    Sources are merged in priority order (entry_points > user > project > builtin).
    Later sources can override earlier ones with the same name.

    Args:
        group: Entry point group name for pip-installed extensions.
        include_entry_points: Whether to discover pip-installed extensions.
        include_user: Whether to discover user-level extensions.
        include_project: Whether to discover project-level extensions.
        include_builtin: Whether to discover built-in extensions.

    Returns:
        Mapping of extension name to setup callable.
    """
    merged: dict[str, ExtensionSetup] = {}

    if include_builtin:
        merged.update(_discover_builtin_plugins())
    if include_project:
        merged.update(_discover_project_plugins())
    if include_user:
        merged.update(_discover_user_plugins())
    if include_entry_points:
        merged.update(_discover_entry_points(group))

    return merged
