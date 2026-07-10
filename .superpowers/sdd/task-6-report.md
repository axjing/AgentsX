# Task 6 Report: Context Profile System

**Status: DONE**

## Summary

Added a runtime posture detection system that automatically determines whether the
agent is working in a coding project (git repo with source files) or a general
directory. This is the foundation for future context-aware behavior.

## Files Created

| File | Description |
|------|-------------|
| `d:\An\CODE\AgentsX\agentsx\core\profile.py` | `AgentPosture` enum, `ContextProfile` frozen dataclass, built-in profiles, `get_profile()`, `resolve_runtime_mode()` |
| `d:\An\CODDE\AgentsX\tests\test_profile.py` | 5 test functions covering frozen dataclass, git repo detection, empty dir, toolset filter, and profile registry |

## Implementation Details

### `AgentPosture(str, Enum)`
String-backed enum with `CODING = "coding"` and `GENERAL = "general"` values.

### `ContextProfile(frozen=True)`
Immutable dataclass with fields: `name`, `posture`, `toolset_filter` (frozenset),
`system_hint`. Two built-in profiles:

- **coding**: `toolset_filter=frozenset({"read", "write", "exec", "orchestration"})`,
  system hint: "You are working in a coding project."
- **general**: Empty toolset filter, no hint.

### `resolve_runtime_mode(cwd)`
1. Converts cwd to `Path` (defaults to `Path.cwd()`)
2. Checks for `.git` directory in cwd or any parent via `_has_git_root()`
3. If git repo found, scans for source files via `_has_source_files()`:
   - Uses `Path.rglob("*")` with max 50 entries budget
   - Skips hidden (dot-prefixed) directories like `.git`, `.venv`, `.mypy_cache`
   - Recognizes 30+ source extensions (.py, .ts, .tsx, .js, .go, .rs, etc.)
4. If source files found -> returns "coding" profile
5. Otherwise -> returns "general" profile

### Key Deviation from Brief

The brief's `_has_source_files()` used `path.iterdir()` which only checks
top-level files. The AgentsX repo has source files in subdirectories
(`agentsx/`, `tests/`), not at the root. Fixed by using `Path.rglob("*")`
with a 50-entry budget and skipping hidden directories (which would otherwise
exhaust the budget on `.git/` internals).

## Validation Results

| Check | Result |
|-------|--------|
| `ruff check` | All checks passed |
| `ruff format --check` | 90 files already formatted |
| `mypy --strict` | Success, no issues in 87 source files |
| `pytest tests/test_profile.py` | 5 passed |
| `pytest` (full suite) | 252 passed, 1 warning (pre-existing) |

## Commit

```
200ef9f feat(core): add ContextProfile system for runtime posture detection
```

## Concerns

None. The implementation meets all requirements from the brief.

---

## Post-Review Fixes (Task 6 Review Findings)

### Fixes Applied

| # | Severity | File:Line | Issue | Fix |
| --- | --- | --- | --- | --- |
| 1 | Important | `tests/test_profile.py:40` | `assert mode.toolset_filter is not None` trivially true for any frozenset | Changed to `assert mode.toolset_filter == frozenset({"read", "write", "exec", "orchestration"})` |
| 2 | Important | `agentsx/core/profile.py:7` | Misplaced comment "Maximum number of directory entries..." above `_SOURCE_EXTENSIONS` | Moved comment above `_SCAN_MAX_ENTRIES` where it belongs |
| 3 | Important | `agentsx/core/profile.py:31-32` | `.bash` and `.zsh` are not valid file extensions (shell scripts use `.sh`) | Removed both entries from `_SOURCE_EXTENSIONS` |
| 4 | Minor | `tests/test_profile.py:14-21` | Frozen dataclass test only checks `is_dataclass()`, not immutability | Added mutation test that attempts `profile.name = "changed"` and verifies `FrozenInstanceError` is raised |

### Fix Validation Results

| Check | Result |
|-------|--------|
| `ruff check agentsx/ tests/` | All checks passed |
| `pytest tests/test_profile.py` | 5 passed |
| `pytest` (full suite) | 256 passed, 1 warning (pre-existing) |

### Fix Commit

```text
a5f0732 fix(profile): tighten test assertions, remove invalid extensions, fix comment placement
```
