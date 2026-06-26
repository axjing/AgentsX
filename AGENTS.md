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


### 1.5 Design Principles

#### Principle 1: Usability over Performance

* The project’s primary goal is usability
* A secondary goal is to have _reasonable_ performance

We believe the ability to maintain our flexibility to support researchers who are building on top of our abstractions remains critical. We can’t see what the future of workloads will be, but we know we want them to be built first on this platform, and that requires flexibility.

In more concrete terms, we operate in a _usability-first_ manner and try to avoid jumping to _restriction-first_ regimes (for example, static shapes, graph-mode only) without a clear-eyed view of the tradeoffs. Often there is a temptation to impose strict user restrictions upfront because it can simplify implementation, but this comes with risks:

* The performance may not be worth the user friction, either because the performance benefit is not compelling enough or it only applies to a relatively narrow set of subproblems.
* Even if the performance benefit is compelling, the restrictions can fragment the ecosystem into different sets of limitations that can quickly become incomprehensible to users.

We want users to be able to seamlessly move their code built with this framework to different hardware and software platforms, to interoperate with different libraries and frameworks, and to experience the full richness of the framework’s user experience, not a least common denominator subset.

#### Principle 2: Simple Over Easy

Here, we borrow from The Zen of Python:

* _Explicit is better than implicit_
* _Simple is better than complex_

A more concise way of describing these two goals is **Simple Over Easy**. Let’s start with an example because _simple_ and _easy_ are often used interchangeably in everyday English. Consider how one may model computational devices in such a framework:

* **Simple / Explicit (to understand, debug)**
* **Easy / Implicit (to use)**

As a general design philosophy, the project favors exposing simple and explicit building blocks rather than APIs that are easy-to-use by practitioners. The simple version is immediately understandable and debuggable by a new user. The easy solution may let a new user move faster initially, but debugging such a system can be complex: How did the system make its determination? What is the API for plugging into such a system and how are objects represented in its intermediate representation?

Some classic arguments in favor of this sort of design come from foundational literature on distributed computation (**TLDR:** Do not model resources with very different performance characteristics uniformly, the details will leak) and the End-to-End Principle (TLDR: building smarts into the lower layers of the stack can prevent building performant features at higher layers, and often doesn’t work anyway). For example, we could build operator-level or global device movement rules, but the precise choices aren’t obvious and building an extensible mechanism has unavoidable complexity and latency costs.

A caveat here is that this does not mean that higher-level “easy” APIs are not valuable; certainly there is value in, for example, higher layers in the stack to support efficient tensor computations across heterogeneous compute in a large cluster. Instead, what we mean is that focusing on simple lower-level building blocks helps inform the easy API while still maintaining a good experience when users need to leave the beaten path. It also allows space for innovation and the growth of more opinionated tools at a rate we cannot support in the core library, but ultimately benefit from, as evidenced by our rich ecosystem. In other words, not automating at the start allows us to potentially reach levels of good automation faster.

#### Principle 3: Primary Language First with Best-in-Class Language Interoperability

This principle began as **Primary Language First**:

> The framework is not a binding of its primary language into a monolithic C++ core. It is built to be deeply integrated into that language. You can use it naturally like you would use well-established libraries in that ecosystem. You can write your new neural network layers in the language itself, using your favorite libraries and packages such as performance-oriented extensions. Our goal is to not reinvent the wheel where appropriate.

One thing the project has needed to deal with over the years is language runtime overhead: we first rewrote key components in C++, then the majority of operator definitions, then developed an ahead-of-time compilation flow and a C++ frontend.

Still, working in the primary language provides easily the best experience for our users: it is flexible, familiar, and perhaps most importantly, has a huge ecosystem of scientific computing libraries and extensions available for use. This fact motivates some of our most recent contributions, which attempt to hit a Pareto optimal point close to the language usability end of the curve:

* A dynamic bytecode transformation engine capable of speeding up existing eager-mode programs with minimal user intervention.
* Extension points (such as tensor-level function overrides and operator dispatch customization) that have enabled primary-language-first functionality to be built on top of C++ internals, enabling tools like symbolic tracers and composable function transforms respectively.

These design principles are not hard-and-fast rules, but hard-won choices and anchor how we built this project to be the debuggable, hackable, and flexible framework it is today. As we have more contributors and maintainers, we look forward to applying these core principles with you across our libraries and ecosystem. We are also open to evolving them as we learn new things and the technology space evolves, as we know it will.

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
{feat|fix|docs|refactor}[(agent|harness|cli|tools|security|session|extensions|infra|context|workspace|mcp)]: concise English description
```
Examples:
- `feat(agent): add ReAct loop with tool execution`
- `fix(tools): handle empty arguments in grep tool`
- `docs: update README with quick start`
- `refactor: reorganize directory structure for clarity`
- `feat(security): add path guard, command guard, and resource limits`

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
uv run agentsx chat --workspace /path/to/project  # restrict file tools

# Module overview
# agentsx/core/       - Message types, events, errors
# agentsx/context/    - Compaction, trajectory tracking, summarization
# agentsx/provider/   - OpenAI, Anthropic LLM providers
# agentsx/agent/      - ReAct loop, Agent class, subagents
# agentsx/tools/      - Tool system (risk-tiered: read/write/exec/web/orchestration)
# agentsx/security/   - Execution policy, path/command guards, resource limits
# agentsx/extensions/ - Observer-only extension API
# agentsx/session/    - JSONL session storage
# agentsx/workspace/  - Workspace manager, git status, file tree index
# agentsx/cli/        - CLI entry (main.py), slash commands (commands.py), REPL (repl.py)

# Git
git status
git add <file-path>
git commit -m "feat(harness): add session management"
git push
```
