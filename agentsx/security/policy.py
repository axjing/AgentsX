"""Security policy — tool-level access control.

Three-tier decision model inspired by Codex CLI:
    - ``ALLOW``: Execute without confirmation.
    - ``PROMPT``: Ask the user before executing (safe default).
    - ``FORBIDDEN``: Block execution unconditionally.

Rules are evaluated with ``fnmatch`` against a combined
``"tool_name:{json_args}"`` pattern.  More specific rules match first.
"""

import json
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

from agentsx.protocol.messages import Decision
from agentsx.security.command_guard import CommandGuard, ThreatLevel
from agentsx.security.path_guard import PathGuard, is_subpath

if TYPE_CHECKING:
    from agentsx.security.saved_rules import SavedRulesStore


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
        saved_rules_store: "SavedRulesStore | None" = None,
    ) -> None:
        self.rules = rules or []
        self._default = default_decision
        self._allowed_dirs = [d.resolve() for d in (allowed_dirs or [])]
        self._saved_store: SavedRulesStore | None = saved_rules_store
        self._command_guard = CommandGuard()
        self._path_guards = [PathGuard(workspace=d) for d in self._allowed_dirs]

    def evaluate(
        self,
        tool_name: str,
        tool_args: dict[str, object] | None = None,
    ) -> Decision:
        """Evaluate a tool call against the rule list.

        Evaluation order:
        1. Path guard (allowed_dirs) — FORBIDDEN if outside.
        1.5 Command guard — FORBIDDEN if dangerous command.
        2. Saved user rules (always allow/deny) — highest priority.
        3. Built-in rules (fnmatch patterns).
        4. Default decision.

        Args:
            tool_name: The tool's name (e.g. ``"tool_file_read"``, ``"tool_bash"``).
            tool_args: The arguments dict passed to the tool.

        Returns:
            ``ALLOW``, ``PROMPT``, or ``FORBIDDEN``.
        """
        # 1. Path guard
        if self._allowed_dirs and tool_name in (
            "tool_file_read",
            "tool_file_write",
            "tool_file_edit",
            "tool_file_glob",
            "tool_file_grep",
            "tool_bash",
        ):
            if not self._check_path_allowed(tool_name, tool_args or {}):
                return Decision.FORBIDDEN

        # 1.5 Command guard for shell/subprocess execution
        if tool_name in ("tool_bash", "tool_mcp_call"):
            cmd = str(
                (tool_args or {}).get(
                    "command" if tool_name == "tool_bash" else "server_command",
                    "",
                )
            )
            if cmd:
                cmd_check = self._command_guard.check(cmd)
                if cmd_check.level in (
                    ThreatLevel.FORBIDDEN,
                    ThreatLevel.DANGEROUS,
                ):
                    return Decision.FORBIDDEN

        # 2. Saved user rules (persistent allow/deny)
        if self._saved_store is not None:
            path_val = str((tool_args or {}).get("path", ""))
            saved = self._saved_store.evaluate(tool_name, path_val)
            if saved is not None:
                return saved

        # 3. Built-in rules
        args_str = json.dumps(tool_args or {}, sort_keys=True)
        combined = f"{tool_name}:{args_str}"
        for rule in self.rules:
            if fnmatch(combined, rule.pattern):
                return rule.decision

        # 4. Default
        return self._default

    def _check_path_allowed(
        self,
        tool_name: str,
        tool_args: dict[str, object],
    ) -> bool:
        """Check if the target path is within allowed directories."""
        path_val = tool_args.get("path", "")
        if not path_val:
            path_val = tool_args.get("root", "")
        if not path_val and tool_name == "tool_bash":
            path_val = tool_args.get("cwd", "")
        if not path_val or not isinstance(path_val, str):
            return True
        target = Path(path_val)
        return any(guard.check(target).is_safe for guard in self._path_guards)

    @classmethod
    def default(
        cls,
        allowed_dirs: list[Path] | None = None,
        default_decision: Decision | None = None,
    ) -> "ExecutionPolicy":
        """Factory: a sensible default policy.

        Read-only tools are allowed automatically.
        Mutating / shell tools require user confirmation.
        """
        if default_decision is None:
            from agentsx.config import get_settings

            cfg_default = get_settings().policy_default.lower()
            if cfg_default == "allow":
                default_decision = Decision.ALLOW
            elif cfg_default == "forbidden":
                default_decision = Decision.FORBIDDEN
            else:
                default_decision = Decision.PROMPT

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
                Rule("tool_mcp_call:*", Decision.PROMPT),
            ],
            default_decision=default_decision,
            allowed_dirs=allowed_dirs,
        )


__all__ = [
    "Decision",
    "ExecutionPolicy",
    "Rule",
    "is_subpath",
]
