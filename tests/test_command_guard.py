"""Tests for command guard."""

from __future__ import annotations

from agentsx.security.command_guard import (
    CommandGuard,
    ThreatLevel,
)


class TestCommandGuard:
    """CommandGuard threat detection."""

    def test_safe_command(self) -> None:
        guard = CommandGuard()
        result = guard.check("ls -la")
        assert result.level == ThreatLevel.SAFE

    def test_safe_command_echo(self) -> None:
        guard = CommandGuard()
        result = guard.check("echo hello")
        assert result.level == ThreatLevel.SAFE

    def test_forbidden_rm_rf_root(self) -> None:
        guard = CommandGuard()
        result = guard.check("rm -rf /")
        assert result.level == ThreatLevel.FORBIDDEN

    def test_forbidden_fork_bomb(self) -> None:
        guard = CommandGuard()
        result = guard.check(":(){ :|:& };:")
        assert result.level == ThreatLevel.FORBIDDEN

    def test_warning_rm_rf_tmp(self) -> None:
        guard = CommandGuard()
        result = guard.check("rm -rf /tmp/old")
        assert result.level in (ThreatLevel.WARNING, ThreatLevel.FORBIDDEN)

    def test_forbidden_mkfs(self) -> None:
        guard = CommandGuard()
        result = guard.check("mkfs.ext4 /dev/sda1")
        assert result.level == ThreatLevel.FORBIDDEN

    def test_is_allowed(self) -> None:
        guard = CommandGuard()
        assert guard.is_allowed("ls -la")
        assert not guard.is_allowed("rm -rf /")

    def test_add_custom_forbidden(self) -> None:
        guard = CommandGuard()
        guard.add_forbidden("dangerous-cmd*")
        result = guard.check("dangerous-cmd --flag")
        assert result.level == ThreatLevel.FORBIDDEN
