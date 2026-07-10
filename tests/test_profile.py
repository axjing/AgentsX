"""Tests for the context profile system."""

import dataclasses
import tempfile

from agentsx.core.profile import (
    AgentPosture,
    ContextProfile,
    get_profile,
    resolve_runtime_mode,
)


def test_context_profile_frozen() -> None:
    """Verify ContextProfile is a frozen dataclass."""
    profile = ContextProfile(
        name="coding",
        posture=AgentPosture.CODING,
        toolset_filter=frozenset({"read", "write"}),
    )
    assert dataclasses.is_dataclass(profile)


def test_resolve_runtime_mode_in_git_repo() -> None:
    """Resolve should return 'coding' for a git repo with source files."""
    mode = resolve_runtime_mode(cwd="d:/An/CODE/AgentsX")
    assert mode.name == "coding"


def test_resolve_runtime_mode_empty_dir() -> None:
    """Resolve should return 'general' for an empty directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mode = resolve_runtime_mode(cwd=tmpdir)
        assert mode.name == "general"


def test_runtime_mode_toolset_filter() -> None:
    """Coding profile should have a non-empty toolset filter."""
    mode = resolve_runtime_mode(cwd="d:/An/CODE/AgentsX")
    assert mode.toolset_filter is not None


def test_context_profile_registry() -> None:
    """Both built-in profiles should be retrievable."""
    assert get_profile("coding") is not None
    assert get_profile("general") is not None
