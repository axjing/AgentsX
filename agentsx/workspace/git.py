"""Git status awareness for the workspace.

Provides branch name, modified files, and untracked file counts.
Used to inject project context into the agent loop.

Inspired by codex git-utils and hermes git integration.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GitStatus:
    """Snapshot of git repository state."""

    branch: str = ""
    modified_files: list[str] | None = None
    untracked_count: int = 0
    is_dirty: bool = False
    error: str = ""


class GitWatcher:
    """Monitors git repository state."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path.cwd()

    def get_status(self) -> GitStatus:
        """Get current git status."""
        if not (self._root / ".git").is_dir():
            return GitStatus(error="Not a git repository")

        try:
            branch = self._run_git("rev-parse", "--abbrev-ref", "HEAD").strip()
            unstaged = self._run_git("diff", "--name-only").strip().splitlines()
            staged = (
                self._run_git("diff", "--cached", "--name-only").strip().splitlines()
            )
            seen: set[str] = set()
            modified: list[str] = []
            for file_path in unstaged + staged:
                cleaned = file_path.strip()
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    modified.append(cleaned)

            untracked_raw = self._run_git(
                "ls-files", "--others", "--exclude-standard"
            ).strip()
            untracked_files = [f for f in untracked_raw.splitlines() if f.strip()]
            untracked_count = len(untracked_files)

            return GitStatus(
                branch=branch,
                modified_files=modified,
                untracked_count=untracked_count,
                is_dirty=bool(modified) or untracked_count > 0,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return GitStatus(error=str(exc))

    def _run_git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self._root)] + list(args),
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout
