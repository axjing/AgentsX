"""Path traversal detection and workspace confinement.

Inspired by hermes-agent ``path_security.py`` and codex ``file_safety.py``.
Detects symlink attacks, path traversal, and workspace escape attempts.

Windows-specific protections:
    - Junction points (reparse points) can redirect outside the workspace
      without being a symlink. Checked via ``os.stat()`` and reparse tags.
    - Hardlinks point to the same inode as another file. If the original
      inode is outside the workspace, the hardlink is a workspace escape.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from agentsx.security.policy import is_subpath


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
        - Junction point / reparse point detection (Windows)
        - Hardlink workspace escape detection
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
        allow_hardlinks: bool = False,
    ) -> None:
        self._workspace = workspace.resolve() if workspace else None
        self._allow_symlinks = allow_symlinks
        self._allow_hardlinks = allow_hardlinks

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

        # Resolve symlinks, junction points, and normalize
        try:
            resolved = Path(os.path.realpath(str(target)))
        except (OSError, RuntimeError) as exc:
            return PathCheckResult(
                is_safe=False,
                resolved=target,
                reason=f"Cannot resolve path: {exc}",
            )

        # Check for symlinks in original path
        if not self._allow_symlinks:
            result = self._check_symlinks(target)
            if not result.is_safe:
                return result

        # Check for junction points / reparse points (Windows)
        if not self._allow_symlinks:
            result = self._check_reparse_points(target)
            if not result.is_safe:
                return result

        # Check for hardlinks
        if not self._allow_hardlinks:
            result = self._check_hardlinks(target)
            if not result.is_safe:
                return result

        # Check workspace boundary
        if self._workspace and not is_subpath(resolved, self._workspace):
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

    # ── Internal checks ───────────────────────────────────────

    def _check_symlinks(self, target: Path) -> PathCheckResult:
        """Check for symlinks in path components."""
        accumulated = Path()
        for component in target.parts:
            accumulated = accumulated / component
            if accumulated.is_symlink():
                return PathCheckResult(
                    is_safe=False,
                    resolved=target,
                    reason=f"Symlink detected in path: {component}",
                )
        return PathCheckResult(is_safe=True, resolved=target)

    def _check_reparse_points(self, target: Path) -> PathCheckResult:
        """Check for Windows junction points / reparse points.

        Junction points (IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003)
        can redirect to paths outside the workspace without being
        symlinks. On Python < 3.13, ``Path.resolve()`` may not
        follow these, so we check manually.
        """
        accumulated = Path()
        for component in target.parts:
            accumulated = accumulated / component
            if not accumulated.exists():
                continue
            try:
                st = os.stat(str(accumulated), follow_symlinks=False)
                # st_reparse_tag is available on Python 3.10+
                if hasattr(st, "st_reparse_tag"):
                    if st.st_reparse_tag != 0:
                        return PathCheckResult(
                            is_safe=False,
                            resolved=target,
                            reason=f"Junction/reparse point detected: {component}",
                        )
                # Fall back: check if it's a directory that is not a
                # regular symlink but may be a junction
                elif accumulated.is_dir() and os.path.islink(str(accumulated)):
                    return PathCheckResult(
                        is_safe=False,
                        resolved=target,
                        reason=f"Symlink/junction detected: {component}",
                    )
            except OSError:
                pass
        return PathCheckResult(is_safe=True, resolved=target)

    def _check_hardlinks(self, target: Path) -> PathCheckResult:
        """Check if a path is a hardlink to a file outside the workspace.

        Hardlinks share the same inode as the original file. If the
        resolved path escapes the workspace, the file is a hardlink
        to something outside the allowed area.
        """
        if not target.exists() or not self._workspace:
            return PathCheckResult(is_safe=True, resolved=target)
        resolved = Path(os.path.realpath(str(target)))
        if not is_subpath(resolved, self._workspace):
            return PathCheckResult(
                is_safe=False,
                resolved=target,
                reason=f"Hardlink to file outside workspace: {target}",
            )
        return PathCheckResult(is_safe=True, resolved=target)


def _has_traversal_pattern(path: str) -> bool:
    """Detect path traversal patterns like ../ or ..\\."""
    parts = path.replace("\\", "/").split("/")
    return ".." in parts
