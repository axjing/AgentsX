# Task Brief: Task 6 - Context Profile System

## Context

AgentsX has no runtime posture detection. This task adds a frozen `ContextProfile` system to detect coding vs general posture.

## What This Task Does

Create `ContextProfile` frozen dataclass with built-in profiles for "coding" and "general". Implement `resolve_runtime_mode()` that detects git repo with source files.

## Files to Create

1. `agentsx/core/profile.py` — ContextProfile, AgentPosture enum, resolve_runtime_mode()
2. `tests/test_profile.py` — Tests

## Exact Implementation

```python
class AgentPosture(str, Enum):
    CODING = "coding"
    GENERAL = "general"

@dataclass(frozen=True)
class ContextProfile:
    name: str
    posture: AgentPosture
    toolset_filter: frozenset[str] = frozenset()
    system_hint: str = ""

_PROFILES = {
    "coding": ContextProfile(name="coding", posture=AgentPosture.CODING,
                             toolset_filter=frozenset({"read", "write", "exec", "orchestration"}),
                             system_hint="You are working in a coding project."),
    "general": ContextProfile(name="general", posture=AgentPosture.GENERAL,
                              toolset_filter=frozenset(), system_hint=""),
}

def get_profile(name: str) -> ContextProfile | None:
    return _PROFILES.get(name)

def resolve_runtime_mode(cwd: str | Path | None = None) -> ContextProfile:
    """Returns 'coding' if in git repo with source files, else 'general'."""
```

## Tests

```python
def test_context_profile_frozen() -> None:
    import dataclasses
    profile = ContextProfile(name="coding", posture=AgentPosture.CODING,
                             toolset_filter=frozenset({"read", "write"}))
    assert dataclasses.is_dataclass(profile)

def test_resolve_runtime_mode_in_git_repo() -> None:
    mode = resolve_runtime_mode(cwd="d:/An/CODE/AgentsX")
    assert mode.name == "coding"

def test_resolve_runtime_mode_empty_dir() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        mode = resolve_runtime_mode(cwd=tmpdir)
        assert mode.name == "general"

def test_runtime_mode_toolset_filter() -> None:
    mode = resolve_runtime_mode(cwd="d:/An/CODE/AgentsX")
    assert mode.toolset_filter is not None

def test_context_profile_registry() -> None:
    assert get_profile("coding") is not None
    assert get_profile("general") is not None
```

## Important Constraints

- Use `(str, Enum)` mixin for AgentPosture
- `@dataclass(frozen=True)` for ContextProfile
- Google-style docstrings, full type annotations
- Line length max 88 characters, `git add <file-path>` only

## Validation Required Before Commit

```bash
uv run ruff check agentsx/ tests/
uv run ruff format --check agentsx/ tests/
uv run mypy agentsx/ tests/ --strict
uv run pytest tests/test_profile.py -v
uv run pytest -v
```

## Report

Write detailed report to `d:/An/CODE/AgentsX/.superpowers/sdd/task-6-report.md`.
Return status as one of: DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, BLOCKED.
