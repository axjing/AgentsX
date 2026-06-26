"""CLI entry point — typer interactive chat loop.

Usage::

    agentsx chat
    agentsx chat --model claude-sonnet-4-20250514 --no-tools
    agentsx run "Summarize README.md"
"""

from __future__ import annotations

import asyncio
import logging

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agentsx.agent.loop import run_agent_loop
from agentsx.cli import commands
from agentsx.config import get_settings
from agentsx.core.errors import SessionError
from agentsx.core.types import (
    AgentMessage,
    Decision,
    ErrorEvent,
    MessageRole,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolExecutionEvent,
)
from agentsx.provider import create_provider
from agentsx.security import ExecutionPolicy
from agentsx.session import SessionStore
from agentsx.tools import ToolRegistry
from agentsx.tools.builtin import ALL_TOOLS

console = Console()
logger = logging.getLogger(__name__)

app = typer.Typer(
    name="agentsx",
    help="AgentsX — Agent Harness CLI",
    no_args_is_help=True,
)


@app.command()
def chat(
    model: str = typer.Option(
        "",
        "--model",
        "-m",
        help="Model identifier (default from AGENTSX_MODEL_NAME)",
    ),
    system: str = typer.Option(
        "",
        "--system",
        "-s",
        help="System prompt override",
    ),
    no_tools: bool = typer.Option(
        False,
        "--no-tools",
        help="Disable all built-in tools",
    ),
    max_steps: int = typer.Option(
        0,
        "--max-steps",
        help="Max tool-calling iterations",
    ),
    allow_all: bool = typer.Option(
        False,
        "--allow-all",
        help="Skip policy checks (ALLOW all tools)",
    ),
    session: str = typer.Option(
        "",
        "--session",
        help="Session ID to resume (creates new if empty)",
    ),
    timeout: float = typer.Option(
        0,
        "--timeout",
        help="Wall-clock timeout for agent loop (seconds, 0=disabled)",
    ),
) -> None:
    """Start an interactive chat session with an AI agent."""
    asyncio.run(
        _async_chat(model, system, no_tools, max_steps, allow_all, session, timeout),
    )


@app.command()
def run(
    prompt: str = typer.Argument(..., help="Single prompt to execute"),
    model: str = typer.Option(
        "",
        "--model",
        "-m",
        help="Model identifier",
    ),
    no_tools: bool = typer.Option(
        False,
        "--no-tools",
        help="Disable all built-in tools",
    ),
    max_steps: int = typer.Option(
        0,
        "--max-steps",
        help="Max tool-calling iterations",
    ),
    allow_all: bool = typer.Option(
        False,
        "--allow-all",
        help="Skip policy checks (ALLOW all tools)",
    ),
    timeout: float = typer.Option(
        0,
        "--timeout",
        help="Wall-clock timeout for agent loop (seconds, 0=disabled)",
    ),
) -> None:
    """Execute a single prompt and exit.

    Useful for scripting and piping output.
    """
    asyncio.run(
        _async_run(prompt, model, no_tools, max_steps, allow_all, timeout),
    )


async def _async_run(
    prompt: str,
    model_name: str,
    no_tools: bool,
    max_steps: int,
    allow_all: bool = False,
    timeout: float = 0,
) -> None:
    settings = get_settings()
    resolved_model = model_name or settings.model_name
    provider = create_provider(model_name=resolved_model)

    messages: list[AgentMessage] = []
    system_prompt = settings.system_prompt
    if system_prompt:
        messages.append(
            AgentMessage(role=MessageRole.SYSTEM, content=system_prompt),
        )
    messages.append(AgentMessage(role=MessageRole.USER, content=prompt))

    registry: ToolRegistry | None = None
    if not no_tools:
        registry = ToolRegistry()
        registry.register_all(*ALL_TOOLS)

    steps = max_steps or settings.max_steps

    if allow_all:
        policy = ExecutionPolicy(default_decision=Decision.ALLOW)
    else:
        policy = ExecutionPolicy.default()

    loop_timeout = timeout or settings.loop_timeout
    result_parts: list[str] = []
    async for event in run_agent_loop(
        provider,
        messages,
        steps,
        registry,
        policy=policy,
        timeout=loop_timeout,
    ):
        if isinstance(event, ModelResponseEvent) and not event.delta:
            result_parts.append(event.content)
        elif isinstance(event, ToolExecutionEvent):
            tc = event.tool_call
            args_str = ", ".join(f"{k}={v!r}" for k, v in tc.arguments.items())
            console.print(
                f"[dim]Tool: {tc.name}({args_str})[/dim] "
                f"{'✓' if not event.result.is_error else '✗'}",
            )
        elif isinstance(event, ErrorEvent):
            console.print(f"[red]Error: {event.error}[/red]")

    if result_parts:
        console.print("\n".join(result_parts))


async def _async_chat(
    model_name: str,
    system_prompt: str,
    no_tools: bool,
    max_steps: int,
    allow_all: bool = False,
    session_id: str = "",
    timeout: float = 0,
) -> None:
    settings = get_settings()

    # ── Resolve provider ──────────────────────────────────────────────
    resolved_model = model_name or settings.model_name
    provider = create_provider(model_name=resolved_model)

    # ── Session store ────────────────────────────────────────────────
    store = SessionStore()
    if session_id:
        try:
            sess = store.get(session_id)
            messages = store.get_messages(session_id)
            shown_model = sess.model_name
        except SessionError:
            console.print(
                f"[yellow]Session '{session_id}' not found, starting fresh.[/yellow]",
            )
            sess = store.create(model_name=resolved_model)
            messages = []
            shown_model = resolved_model
    else:
        sess = store.create(model_name=resolved_model)
        messages = []
        shown_model = resolved_model

    # ── Conversation history (shared across turns) ───────────────────
    prompt_text = system_prompt or settings.system_prompt
    if prompt_text:
        messages.append(
            AgentMessage(role=MessageRole.SYSTEM, content=prompt_text),
        )

    # ── Tool registry ────────────────────────────────────────────────
    registry: ToolRegistry | None = None
    if not no_tools:
        registry = ToolRegistry()
        registry.register_all(*ALL_TOOLS)

    steps = max_steps or settings.max_steps

    # ── Security policy ──────────────────────────────────────────────
    if allow_all:
        policy = ExecutionPolicy(default_decision=Decision.ALLOW)
    else:
        policy = ExecutionPolicy.default()

    # ── Prompt session ───────────────────────────────────────────────
    session = PromptSession[str](history=InMemoryHistory())

    # ── Welcome ──────────────────────────────────────────────────────
    info = Table.grid(padding=(0, 1))
    info.add_column()
    info.add_row("Model", shown_model)
    info.add_row("Session", f"{sess.id[:12]}  {sess.title}")
    if registry:
        tool_names = ", ".join(t.name for t in registry.list_tools())
        info.add_row("Tools", tool_names)
    info.add_row("Policy", "allow_all" if allow_all else "default")
    console.print(
        Panel.fit(
            "[bold]AgentsX Chat[/bold]",
            border_style="blue",
        ),
    )
    console.print(info)
    print()  # noqa: T201

    # ── Main loop ────────────────────────────────────────────────────
    loop_timeout = timeout or settings.loop_timeout
    while True:
        try:
            user_input = await session.prompt_async(">>> ")
        except (EOFError, KeyboardInterrupt):
            console.print()
            break

        user_input = user_input.strip()
        if not user_input:
            continue
        if user_input.startswith("/"):
            new_id = _handle_command(user_input, messages, store, sess.id)
            if new_id is not None and new_id != sess.id:
                # Session switch: reload messages
                sess = store.get(new_id)
                messages = store.get_messages(new_id)
                console.print(
                    f"[dim]Loaded session {sess.id[:12]}"
                    f" ({len(messages)} messages)[/dim]",
                )
            continue

        user_msg = AgentMessage(role=MessageRole.USER, content=user_input)
        messages.append(user_msg)
        store.append(sess.id, user_msg)

        # ── Process agent loop ───────────────────────────────────────
        content_buffer: list[str] = []
        async for event in run_agent_loop(
            provider,
            messages,
            steps,
            registry,
            policy=policy,
            timeout=loop_timeout,
        ):
            if isinstance(event, ModelRequestEvent):
                console.print("[dim]Processing...[/dim]")

            elif isinstance(event, ModelResponseEvent):
                if event.delta:
                    content_buffer.append(event.content)
                    console.print(event.content, end="")
                else:
                    # Persist the assistant message
                    if event.content:
                        store.append(
                            sess.id,
                            AgentMessage(
                                role=MessageRole.ASSISTANT,
                                content=event.content,
                            ),
                        )
                    console.print()

            elif isinstance(event, ToolExecutionEvent):
                _display_tool_event(event)
                # Persist tool execution
                store.append(
                    sess.id,
                    AgentMessage(
                        role=MessageRole.TOOL,
                        content=event.result.content,
                        tool_call_id=event.result.tool_call_id,
                        name=event.tool_call.name,
                    ),
                )

            elif isinstance(event, ErrorEvent):
                console.print(f"[red]Error: {event.error}[/red]")

        console.print()


def _display_tool_event(event: ToolExecutionEvent) -> None:
    """Print a tool-execution event to the console."""
    tc = event.tool_call
    tr = event.result
    prefix = "[green]✓[/green]" if not tr.is_error else "[red]✗[/red]"
    args_str = ", ".join(f"{k}={v!r}" for k, v in tc.arguments.items())
    snippet = tr.content[:300]
    if len(tr.content) > 300:
        snippet += " ..."
    console.print(
        Panel(
            f"[dim]{args_str}[/dim]\n{snippet}",
            title=f"{prefix} {tc.name}",
            border_style="green" if not tr.is_error else "red",
        ),
    )


def _handle_command(
    cmd: str,
    messages: list[AgentMessage],
    store: SessionStore | None = None,
    session_id: str = "",
) -> str | None:
    """Process a slash command typed by the user.

    Args:
        cmd: The raw command line.
        messages: Current conversation messages (modified in-place for /clear).
        store: SessionStore instance (required for session commands).
        session_id: Current session ID.

    Returns:
        New session ID if the session was switched, or None.
    """
    parts = cmd.split()
    command = parts[0].lower()

    if command in ("/exit", "/quit"):
        raise SystemExit(0)

    if command == "/help":
        console.print(commands.cmd_help())
        return None

    if command == "/clear":
        messages.clear()
        console.print("[dim]History cleared.[/dim]")
        return None

    # ── Session commands ─────────────────────────────────────────────
    if store is None:
        console.print("[yellow]Session store not available.[/yellow]")
        return None

    if command == "/sessions":
        msg, _ = commands.cmd_sessions(store, session_id)
        console.print(msg)
        return None

    if command == "/session" and len(parts) >= 3 and parts[1] == "show":
        msg, _ = commands.cmd_session_show(store, session_id, parts[2])
        console.print(msg)
        return None

    if command == "/session" and len(parts) >= 3 and parts[1] == "switch":
        msg, new_id = commands.cmd_session_switch(store, session_id, parts[2])
        console.print(msg)
        return new_id

    if command == "/new":
        title = " ".join(parts[1:]) if len(parts) > 1 else ""
        msg, new_id = commands.cmd_new(store, session_id, title)
        console.print(msg)
        return new_id

    if command == "/delete" and len(parts) >= 2:
        msg, _ = commands.cmd_delete(store, session_id, parts[1])
        console.print(msg)
        return None

    if command == "/branch" and len(parts) >= 2:
        title = " ".join(parts[2:]) if len(parts) > 2 else ""
        msg, new_id = commands.cmd_branch(store, session_id, parts[1], title)
        console.print(msg)
        return new_id

    if command == "/title" and len(parts) >= 2:
        title = " ".join(parts[1:])
        msg, _ = commands.cmd_title(store, session_id, title)
        console.print(msg)
        return None

    console.print(f"[yellow]Unknown command: {command}.  Try /help[/yellow]")
    return None
