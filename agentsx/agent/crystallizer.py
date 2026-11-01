"""Autonomous Recursive Self-Improvement (RSI) crystallizer.

Automatically observes failure-and-recovery patterns in tool execution
trajectories and crystallizes actionable rules into persistent memory
without requiring manual user intervention.
"""

from dataclasses import dataclass
from pathlib import Path

from agentsx.protocol import ToolResult


@dataclass(frozen=True)
class CrystallizedRule:
    """A rule automatically synthesized from recovered execution failures."""

    rule: str
    source_tool: str
    failure_reason: str
    scope: str = "project"


class AutonomousCrystallizer:
    """Detects recovered failures and crystallizes learned rules to memory."""

    def __init__(self, workspace_root: Path | None = None) -> None:
        self._workspace_root = workspace_root or Path.cwd()
        self._pending_failures: dict[str, tuple[dict[str, object], str]] = {}
        self._crystallized_rules: list[CrystallizedRule] = []

    @property
    def crystallized_rules(self) -> list[CrystallizedRule]:
        """Rules crystallized during this session."""
        return list(self._crystallized_rules)

    def record_tool_result(
        self,
        tool_name: str,
        arguments: dict[str, object],
        result: ToolResult,
    ) -> CrystallizedRule | None:
        """Observe a tool execution result and crystallize rules on recovery.

        Args:
            tool_name: Name of tool executed.
            arguments: Arguments passed to the tool.
            result: The resulting ToolResult.

        Returns:
            CrystallizedRule if a recovery pattern was recognized and saved,
            else None.
        """
        key = self._get_tool_target_key(tool_name, arguments)

        if result.is_error:
            # Store failure state for this tool target
            self._pending_failures[key] = (arguments, result.content)
            return None

        if result.is_success and key in self._pending_failures:
            # Recovered from previous failure! Synthesize learned rule.
            failed_args, err_content = self._pending_failures.pop(key)
            rule = self._synthesize_rule(
                tool_name=tool_name,
                failed_args=failed_args,
                success_args=arguments,
                error_message=err_content,
            )
            if rule is not None:
                self._persist_rule(rule)
                self._crystallized_rules.append(rule)
                return rule

        return None

    def _get_tool_target_key(
        self,
        tool_name: str,
        arguments: dict[str, object],
    ) -> str:
        """Create a correlation key to match failed and recovered attempts."""
        if tool_name in ("tool_file_edit", "tool_file_write", "tool_file_read"):
            return f"{tool_name}:{arguments.get('path', '')}"
        if tool_name == "tool_bash":
            cmd = str(arguments.get("command", ""))
            tokens = cmd.strip().split()
            # Correlate commands operating on a specific script/file
            if len(tokens) > 1:
                return f"tool_bash:target:{tokens[1]}"
            base_cmd = tokens[0] if tokens else "bash"
            return f"tool_bash:{base_cmd}"
        return tool_name

    def _synthesize_rule(
        self,
        tool_name: str,
        failed_args: dict[str, object],
        success_args: dict[str, object],
        error_message: str,
    ) -> CrystallizedRule | None:
        """Derive an actionable rule from failure and successful recovery."""
        err_lower = error_message.lower()

        if tool_name == "tool_file_edit":
            path = str(success_args.get("path", ""))
            if "matches" in err_lower and "locations" in err_lower:
                return CrystallizedRule(
                    rule=(
                        f"When editing '{path}', include sufficient surrounding "
                        "context lines to avoid multi-match ambiguity."
                    ),
                    source_tool=tool_name,
                    failure_reason="ambiguous multi-match",
                )
            if "not found" in err_lower:
                return CrystallizedRule(
                    rule=(
                        f"When modifying '{path}', verify target file content "
                        "and exact line formatting first before replacing."
                    ),
                    source_tool=tool_name,
                    failure_reason="target string not found",
                )

        if tool_name == "tool_bash":
            failed_cmd = str(failed_args.get("command", ""))
            success_cmd = str(success_args.get("command", ""))

            if "not found" in err_lower or "is not recognized" in err_lower:
                failed_bin = failed_cmd.strip().split()[0] if failed_cmd.strip() else ""
                success_bin = (
                    success_cmd.strip().split()[0] if success_cmd.strip() else ""
                )
                if failed_bin and success_bin and failed_bin != success_bin:
                    return CrystallizedRule(
                        rule=(
                            f"Command '{failed_bin}' is unavailable on this host; "
                            f"use '{success_bin}' instead."
                        ),
                        source_tool=tool_name,
                        failure_reason=f"command {failed_bin} not found",
                    )

            if "syntax error" in err_lower or "unknown option" in err_lower:
                return CrystallizedRule(
                    rule=(
                        f"Avoid command syntax '{failed_cmd}'; "
                        f"prefer verified command '{success_cmd}'."
                    ),
                    source_tool=tool_name,
                    failure_reason="command syntax or option failure",
                )

        return None

    def _persist_rule(self, rule: CrystallizedRule) -> None:
        """Append the synthesized rule to the project memory file."""
        memory_path = self._workspace_root / ".agentsx" / "memory.md"
        try:
            memory_path.parent.mkdir(parents=True, exist_ok=True)
            existing_lines: list[str] = []
            if memory_path.is_file():
                existing_lines = memory_path.read_text(encoding="utf-8").splitlines()

            rule_line = f"- {rule.rule}"
            if rule_line not in existing_lines:
                with memory_path.open("a", encoding="utf-8") as f:
                    if existing_lines and not existing_lines[-1].endswith("\n"):
                        f.write("\n")
                    f.write(f"{rule_line}\n")
        except OSError:
            pass
