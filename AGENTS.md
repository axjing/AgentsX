# AgentsX AI Agent Specification

## 1. Overview

### 1.1 Purpose
Defines mandatory behavioral and coding rules for all AI coding agents operating in this repository. All AI-generated code, file modifications, shell commands, Git operations, and comments must comply.

### 1.2 Scope
Python and documentation. TypeScript is deferred for future Web UI.

### 1.3 Rule Priority (Strict)
1. Explicit user instructions (confirm if conflicting)
2. This document
3. Language official standards (PEP8)
4. Community conventions

### 1.4 Core Principles
- **Correctness**: Resolve issues completely. No skipped validation, deferred fixes, or suboptimal implementations.
- **Session isolation**: No cross-session file modification or overwriting.
- **Confirmation on conflict**: Pause and request confirmation for rule conflicts.

---

## 2. Agent Behavior

### 2.1 Output
- Concise, objective, technical-only. No emojis, flattery, or redundant politeness.
- English in formal technical writing style.

### 2.2 Workflow
- Answer questions completely before code edits.
- For feedback: state agree/disagree in first sentence, then reasoning and revision.

---

## 3. Development Environment

### 3.1 Python
- Virtual environment: `.venv` (project-local, via `uv venv`).
- Activate before running/linting/committing: `.venv\Scripts\activate` (Windows) or `source .venv/bin/activate` (Unix).
- Manage dependencies with `uv sync`, `uv add`, `uv remove`.
- Python 3.10 minimum. No `StrEnum` — use `(str, Enum)` mixin. `from __future__ import annotations` enables `X | Y` in annotations.

### 3.2 TypeScript/JavaScript
Not yet in use. When added, depend on `package.json` + `package-lock.json` consistency.

---

## 4. Validation

### 4.1 Lint
```bash
uv run ruff check agentsx/ tests/
uv run ruff format --check agentsx/ tests/
```

### 4.2 Type Check
```bash
uv run mypy agentsx/ tests/ --strict
```

### 4.3 Test
```bash
uv run python -m pytest -v
```

### 4.4 Line Length
- Python: max **88** characters per line (ruff config).

---

## 5. Python Standards

### 5.1 Formatting
- Indent: 4 spaces. Tabs prohibited.
- No trailing spaces. One blank line at file end.
- Two blank lines between module-level functions/classes.
- One blank line between class methods.
- Line wrapping: implicit parentheses. Backslash continuation prohibited.

### 5.2 Naming
| Element | Convention |
|---------|-----------|
| Files/modules/packages | `snake_case` |
| Functions/variables | `snake_case` |
| Constants | `UPPER_SNAKE_CASE` |
| Classes/Exceptions | `PascalCase` |
| Private members | `_prefix` |

### 5.3 Imports (Hard)
- All at file top. Inline/dynamic/`__import__` prohibited.
- No wildcard (`from X import *`).
- Order: Standard Library → Third-party → Project Internal → Relative.
- `from __future__ import annotations` in every file.

### 5.4 Docstrings
- **Google-style only**. Sphinx (`:param:`, `:return:`) prohibited.
- Required for: modules, classes, public functions, complex private functions.
- Fields: `Args:`, `Returns:`, `Raises:` (on demand).

### 5.5 Type Annotations
- Full annotations on all variables, parameters, return values.
- `Any` prohibited except for unavoidable third-party dynamic interfaces (comment reason).
- Use native generics: `list[]`, `dict[]`, `set[]`.
- Fix type errors by upgrading deps. Never delete code or suppress checks.

### 5.6 Functions & Classes
- Single-use inline logic stays inline. No trivial single-call extraction.
- No mutable default parameters; use `None` placeholder.
- Class order: Docstring → Class Vars → `__init__` → Public → Static/Class → Private → Magic.
- All instance attributes in `__init__`. No dynamic attribute injection.

### 5.7 Exception Handling
- No bare `except:`. Always catch explicit exception types.
- Use `with` context manager for all resource operations.

### 5.8 Python Development Best Practices

#### Ignore Python 2 compatibility

This project uses Python 3+. You should not use the `__future__` module.

If you need to worry about feature compatibility between different 3.xx point releases, check the
closest `pyproject.toml`'s `requires-python` field to see what minimum runtime version is supported.

### 5.9 Platform Support

Tests and features must support Linux, macOS and Windows unless feature is explicitly OS-specific.

This project supports running connected app-server and exec-server on different operating systems. See the `$remote-tests` skill for details about integration testing these configurations.

### 5.10 Project-Specific Conventions
- **Provider pattern**: Subclass `Provider` ABC; register via `register_provider()`, create via `create_provider()`. Each provider takes a `Model(id, provider_name, max_tokens)` dataclass.
- **Agent loop**: `run_agent_loop()` is a pure async generator implementing the ReAct pattern (think → act → observe → repeat). It accepts `provider`, `messages`, `max_steps`, optional `tools` (ToolRegistry), optional `policy` (ExecutionPolicy), and optional `extensions` (ExtensionAPI). Yields `AgentEvent` items.
- **Tool system**: Define tools with the `@tool()` decorator, which auto-generates a JSON Schema. Register in `ToolRegistry`. Built-in tools live in `agentsx/tools/builtin/`.
- **Security**: `ExecutionPolicy` evaluates fnmatch patterns against `"tool_name:{json_args}"`. Default policy ALLOWs read-only tools and PROMPTs mutations.
- **Session**: `SessionStore` stores conversations as JSONL files under `~/.agentsx/sessions/<id>/`. Append-only O(1) writes, zero external deps.
- **Extensions**: `ExtensionAPI` observer-only pattern. `on()` registers handlers, `emit()` fires events (exception-isolated). 7 predefined events. Auto-discovery via `entry_points(group="agentsx.extensions")`.
- **Config**: All config via `AGENTSX_*` environment variables in `agentsx/config.py` (Pydantic Settings).
- **Async**: All I/O-bound functions use `async def`. CLI uses `asyncio.run()`.



---

## 6. Engineering Restrictions

### 6.1 No Hardcoding
- API URLs, ports, file paths, secrets, tokens — all in config/env variables.
- No magic numbers.

### 6.2 Modification Rules
- Delete/disable existing features only after user confirmation.
- Large-scale refactoring: read full file/module first.

### 6.3 3rdparty Directory
- `3rdparty/` is read-only. Never modify files inside it.

---

## 7. Git Workflow

### 7.1 Commit Rules
- Stage only files modified by current session.
- Explicit file path staging only. `git add .` / `git add -A` prohibited.
- Verify with `git status` before commit.

### 7.2 Commit Message Format
```
{feat|fix|docs}[(agent|harness|cli|tools|security|session|extensions|infra)]: concise English description
```
Examples:
- `feat(agent): add ReAct loop with tool execution`
- `fix(tools): handle empty arguments in grep tool`
- `docs: update README with quick start`

### 7.3 Forbidden Commands
`git reset --hard`, `git checkout .`, `git clean -fd`, `git stash`, `git add -A`, `git add .`, `git commit --no-verify`, `git push --force`.

### 7.4 Conflict Handling
- Resolve only in self-modified files.
- Abort rebase and notify user for external file conflicts.

---

## 8. Issue & PR Workflow
- No branch switching without user instruction.
- Inspect PR via `gh pr view`, `gh pr diff`, `git show`.
- Auto-close issues: `closes #1`.

---

## 9. Standard Workflow
1. **Analyze**: Clarify requirements. Read full module for large changes.
2. **Implement**: Follow language spec strictly.
3. **Validate**: Activate env + lint + type-check + test.
4. **Commit**: Explicit stage + standardized message.
5. **Finalize**: Link issues, finish review.

---

## 10. Forbidden Checklist

### Hard Prohibitions
- Bypassing validation (ruff, mypy, pytest)
- Dynamic imports, wildcard imports
- Hardcoding configurable values
- Dangerous Git operations and force push
- Python: Sphinx docstrings, bare except, overuse `Any`, tab indent
- Modifying files under `3rdparty/`

### User Confirmation Required
- Delete/disable existing features
- Modify global configs
- Disable validation rules
- Drop backward compatibility

---

## Appendix: Quick Reference

```bash
# Development
.venv\Scripts\activate                # Windows
source .venv/bin/activate             # Unix
uv sync --extra dev                   # install with dev deps

# Lint & Type Check
uv run ruff check agentsx/ tests/
uv run ruff format --check agentsx/ tests/
uv run mypy agentsx/ tests/ --strict

# Test
uv run python -m pytest -v

# Run CLI
uv run agentsx chat
uv run agentsx chat --model gpt-4o --allow-all

# Git
git status
git add <file-path>
git commit -m "feat(harness): add session management"
git push
```
