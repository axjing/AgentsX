"""Security policy — tool-level access control.

Three-tier decision model inspired by Codex CLI:
    - ``ALLOW``: Execute without confirmation.
    - ``PROMPT``: Ask the user before executing (safe default).
    - ``FORBIDDEN``: Block execution unconditionally.

Rules are evaluated with ``fnmatch`` against a combined
``"tool_name:{json_args}"`` pattern.  More specific rules match first.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from agentsx.core.types import Decision


@dataclass
class Rule:
    """A single security rule.

    The ``pattern`` is matched (via ``fnmatch``) against a combined string
    ``"tool_name:{json_args}"``.  Examples::

        Rule("tool_file_read:*", Decision.ALLOW)            # all read calls allowed
        Rule("tool_bash:rm *", Decision.FORBIDDEN)     # rm forbidden in bash
        Rule("*", Decision.PROMPT)                 # everything else: prompt
    """

    pattern: str
    decision: Decision


class ExecutionPolicy:
    """Tool-call access policy.

    Usage::

        policy = ExecutionPolicy.default()
        decision = policy.evaluate("tool_file_read", {"path": "/tmp/a.txt"})
        # → Decision.ALLOW
    """

    def __init__(
        self,
        rules: list[Rule] | None = None,
        default_decision: Decision = Decision.PROMPT,
        allowed_dirs: list[Path] | None = None,
    ) -> None:
        self.rules = rules or []
        self._default = default_decision
        self._allowed_dirs = [d.resolve() for d in (allowed_dirs or [])]

    def evaluate(
        self,
        tool_name: str,
        tool_args: dict[str, object] | None = None,
    ) -> Decision:
        """Evaluate a tool call against the rule list.

        For filesystem tools (tool_file_read, tool_file_write, tool_file_edit,
        tool_file_glob, tool_file_grep), checks
        that the target path is within ``allowed_dirs`` if configured.

        Args:
            tool_name: The tool's name (e.g. ``"tool_file_read"``, ``"tool_bash"``).
            tool_args: The arguments dict passed to the tool.

        Returns:
            ``ALLOW``, ``PROMPT``, or ``FORBIDDEN``.
        """
        if self._allowed_dirs and tool_name in (
            "tool_file_read",
            "tool_file_write",
            "tool_file_edit",
            "tool_file_glob",
            "tool_file_grep",
        ):
            if not self._check_path_allowed(tool_name, tool_args or {}):
                return Decision.FORBIDDEN

        args_str = json.dumps(tool_args or {}, sort_keys=True)
        combined = f"{tool_name}:{args_str}"
        for rule in self.rules:
            if fnmatch(combined, rule.pattern):
                return rule.decision
        return self._default

    def _check_path_allowed(
        self,
        tool_name: str,
        tool_args: dict[str, object],
    ) -> bool:
        """Check if the target path is within allowed directories."""
        path_val = tool_args.get("path", "")
        if not path_val:
            path_val = tool_args.get("root", ".")
        if not path_val or not isinstance(path_val, str):
            return True
        try:
            target = Path(path_val).resolve()
        except (ValueError, RuntimeError):
            return False
        return any(_is_subpath(target, allowed) for allowed in self._allowed_dirs)

    @classmethod
    def default(cls) -> ExecutionPolicy:
        """Factory: a sensible default policy.

        Read-only tools are allowed automatically.
        Mutating / shell tools require user confirmation.
        """
        return cls(
            rules=[
                Rule("tool_file_read:*", Decision.ALLOW),
                Rule("tool_file_glob:*", Decision.ALLOW),
                Rule("tool_file_grep:*", Decision.ALLOW),
                Rule("tool_web_fetch:*", Decision.ALLOW),
                Rule("tool_web_search:*", Decision.ALLOW),
                Rule("tool_file_write:*", Decision.PROMPT),
                Rule("tool_file_edit:*", Decision.PROMPT),
                Rule("tool_bash:*", Decision.PROMPT),
            ],
        )


def _is_subpath(target: Path, base: Path) -> bool:
    """Return True if *target* is inside *base*."""
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False
