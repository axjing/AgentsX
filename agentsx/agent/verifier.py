"""Proactive code verification and syntax quality gate.

Automatically inspects files modified by the agent (e.g. Python syntax,
JSON validity) to catch errors immediately and steer self-healing before
completing the task.
"""

import ast
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class QualityCheckResult:
    """Result of proactive verification on a single file."""

    path: Path
    is_valid: bool
    file_type: str
    error_message: str = ""


class ProactiveQualityGate:
    """Proactively verifies file modifications for syntax/structural integrity."""

    def verify_file(self, path: str | Path) -> QualityCheckResult:
        """Verify the syntax or format of a modified file.

        Args:
            path: Target file path to check.

        Returns:
            QualityCheckResult containing validation status.
        """
        target = Path(path)
        if not target.is_file():
            return QualityCheckResult(
                path=target,
                is_valid=True,
                file_type="unknown",
            )

        suffix = target.suffix.lower()

        if suffix == ".py":
            return self._verify_python(target)
        if suffix == ".json":
            return self._verify_json(target)

        return QualityCheckResult(
            path=target,
            is_valid=True,
            file_type=suffix or "plain",
        )

    def _verify_python(self, path: Path) -> QualityCheckResult:
        """Verify Python syntax using standard ast.parse."""
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            ast.parse(content, filename=str(path))
            return QualityCheckResult(path=path, is_valid=True, file_type="python")
        except SyntaxError as exc:
            line = exc.lineno or 0
            offset = exc.offset or 0
            msg = exc.msg or "syntax error"
            error_desc = f"line {line}, col {offset}: {msg}"
            return QualityCheckResult(
                path=path,
                is_valid=False,
                file_type="python",
                error_message=error_desc,
            )
        except OSError as exc:
            return QualityCheckResult(
                path=path,
                is_valid=False,
                file_type="python",
                error_message=str(exc),
            )

    def _verify_json(self, path: Path) -> QualityCheckResult:
        """Verify JSON validity using json.loads."""
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            json.loads(content)
            return QualityCheckResult(path=path, is_valid=True, file_type="json")
        except json.JSONDecodeError as exc:
            error_desc = f"line {exc.lineno}, col {exc.colno}: {exc.msg}"
            return QualityCheckResult(
                path=path,
                is_valid=False,
                file_type="json",
                error_message=error_desc,
            )
        except OSError as exc:
            return QualityCheckResult(
                path=path,
                is_valid=False,
                file_type="json",
                error_message=str(exc),
            )

    def verify_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, object],
    ) -> QualityCheckResult | None:
        """Inspect a file modification tool call and verify target if applicable.

        Args:
            tool_name: Name of tool executed.
            arguments: Arguments passed to the tool.

        Returns:
            QualityCheckResult if target was verified, else None.
        """
        if tool_name not in ("tool_file_write", "tool_file_edit"):
            return None

        path_val = arguments.get("path")
        if not path_val or not isinstance(path_val, str):
            return None

        return self.verify_file(path_val)
