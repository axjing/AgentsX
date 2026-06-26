"""Dangerous command detection for shell tool.

Inspired by hermes-agent `threat_patterns.py` and codex `execpolicy`.
Blocks destructive commands and detects injection attempts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from fnmatch import fnmatch


class ThreatLevel(str, Enum):
    """Threat severity for a command."""

    SAFE = "safe"
    WARNING = "warning"
    DANGEROUS = "dangerous"
    FORBIDDEN = "forbidden"


@dataclass
class CommandCheckResult:
    """Result of a command security check."""

    level: ThreatLevel
    reason: str = ""
    matched_pattern: str = ""


# Dangerous commands that are always forbidden (fnmatch patterns)
_FORBIDDEN_PATTERNS: list[str] = [
    "rm -rf /*",
    "rm -rf /",
    "rm -rf ~/*",
    "rm -rf ~",
    ":(){*:*};:",  # fork bomb
    "mkfs.*",
    "dd if=* of=/dev/*",
    "dd if=* of=/dev/*",
    "chmod -R 777 /",
    "chmod -R 000 /",
    "chown -R * /",
    "mv / /dev/null",
    ">/dev/sda*",
    ">>/dev/sda*",
]

# Commands that trigger a warning
_WARNING_PATTERNS: list[str] = [
    "rm -rf*",
    "rm -r*",
    "rm *",
    "chmod*",
    "chown*",
    "mkfifo*",
    "mknod*",
    "mount*",
    "umount*",
    "wget*",
    "curl*|*",  # pipe to shell
    "curl*|*",
    "wget*|*",
    "bash -c*",
    "sh -c*",
    "eval*",
    "exec*",
    "python* -c*",
    "python3* -c*",
]

# Injection patterns
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("pipe-to-dangerous", re.compile(r";\s*(rm|chmod|chown|dd|mkfs)")),
    ("pipe-to-shell", re.compile(r"\|\s*(bash|sh|python|python3|eval|exec)")),
    ("backtick-exec", re.compile(r"`[^`]*(rm|chmod|dd|mkfs)[^`]*`")),
    ("subshell-exec", re.compile(r"\$\(.*?(rm|chmod|dd|mkfs).*?\)")),
    ("echo-pipe-bash", re.compile(r"\b(echo|printf).*\|.*\b(bash|sh)\b")),
    ("cd-then-destruct", re.compile(r"\b(cd|cd\s+/)\s*;\s*(rm|chmod|dd)\b")),
]


class CommandGuard:
    """Validates shell commands for safety.

    Checks performed:
        - Forbidden command patterns (always blocked)
        - Warning patterns (flagged for user review)
        - Shell injection patterns (detected and blocked)

    Usage::

        guard = CommandGuard()
        result = guard.check("rm -rf /tmp/old")
        if result.level == ThreatLevel.FORBIDDEN:
            raise SecurityError(result.reason)
    """

    def __init__(
        self,
        forbidden_patterns: list[str] | None = None,
        warning_patterns: list[str] | None = None,
    ) -> None:
        self._forbidden = forbidden_patterns or _FORBIDDEN_PATTERNS
        self._warning = warning_patterns or _WARNING_PATTERNS

    def check(self, command: str) -> CommandCheckResult:
        """Check a command for threats.

        Args:
            command: The shell command to check.

        Returns:
            CommandCheckResult with threat level and reason.
        """
        normalized = command.strip()

        # Check injection patterns first (highest priority)
        for name, pattern in _INJECTION_PATTERNS:
            if pattern.search(normalized):
                return CommandCheckResult(
                    level=ThreatLevel.FORBIDDEN,
                    reason=f"Shell injection pattern detected: {name}",
                    matched_pattern=name,
                )

        # Check forbidden patterns
        for pattern_str in self._forbidden:
            if fnmatch(normalized, pattern_str):
                return CommandCheckResult(
                    level=ThreatLevel.FORBIDDEN,
                    reason=f"Forbidden command pattern: {pattern_str}",
                    matched_pattern=pattern_str,
                )

        # Check warning patterns
        for pattern_str in self._warning:
            if fnmatch(normalized, pattern_str):
                return CommandCheckResult(
                    level=ThreatLevel.WARNING,
                    reason=f"Warning pattern: {pattern_str}",
                    matched_pattern=pattern_str,
                )

        return CommandCheckResult(level=ThreatLevel.SAFE)

    def is_allowed(self, command: str) -> bool:
        """Quick check: is the command safe to execute?"""
        return self.check(command).level != ThreatLevel.FORBIDDEN

    def add_forbidden(self, pattern: str) -> None:
        """Add a forbidden pattern."""
        self._forbidden.append(pattern)

    def add_warning(self, pattern: str) -> None:
        """Add a warning pattern."""
        self._warning.append(pattern)
