"""Path traversal detection and workspace confinement.

Inspired by hermes-agent `path_security.py` and codex `file_safety.py`.
Detects symlink attacks, path traversal, and workspace escape attempts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class PathCheckResult:
    """Result of a path security check."""

    is_safe: bool
    resolved: Path
    reason: str = ""


class PathGuard:
    """Validates filesystem paths against a workspace boundary.

    Checks performed:
        - Absolute vs relative path resolution
        - Symlink resolution to final target
        - Workspace boundary enforcement
        - Dangerous path pattern detection

    Usage::

        guard = PathGuard(workspace=Path("/workspace"))
        result = guard.check("../etc/passwd")
        if not result.is_safe:
            raise SecurityError(result.reason)
    """

    def __init__(
        self,
        workspace: Path | None = None,
        allow_symlinks: bool = False,
    ) -> None:
        self._workspace = workspace.resolve() if workspace else None
        self._allow_symlinks = allow_symlinks

    @property
    def workspace(self) -> Path | None:
        return self._workspace

    def check(self, path: str | Path) -> PathCheckResult:
        """Validate a path against the workspace boundary.

        Args:
            path: The path to validate.

        Returns:
            PathCheckResult with safety status and resolved path.
        """
        target = Path(path)

        # Resolve symlinks and normalize
        try:
            resolved = target.resolve()
        except (OSError, RuntimeError) as exc:
            return PathCheckResult(
                is_safe=False,
                resolved=target,
                reason=f"Cannot resolve path: {exc}",
            )

        # Check for symlink in original path
        if not self._allow_symlinks:
            for component in target.parts:
                check = target.parent / component
                if check.is_symlink():
                    return PathCheckResult(
                        is_safe=False,
                        resolved=resolved,
                        reason=f"Symlink detected in path: {component}",
                    )

        # Check workspace boundary
        if self._workspace and not _is_subpath(resolved, self._workspace):
            return PathCheckResult(
                is_safe=False,
                resolved=resolved,
                reason=f"Path escapes workspace: {resolved}",
            )

        # Check for traversal patterns
        if _has_traversal_pattern(str(target)):
            return PathCheckResult(
                is_safe=False,
                resolved=resolved,
                reason="Path contains traversal patterns (../)",
            )

        return PathCheckResult(is_safe=True, resolved=resolved)

    def is_allowed(self, path: str | Path) -> bool:
        """Quick check: is the path safe?"""
        return self.check(path).is_safe


def _is_subpath(target: Path, base: Path) -> bool:
    """Return True if *target* is inside *base* (or equal to it)."""
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False


def _has_traversal_pattern(path: str) -> bool:
    """Detect path traversal patterns like ../ or ..\\."""
    parts = path.replace("\\", "/").split("/")
    return ".." in parts
