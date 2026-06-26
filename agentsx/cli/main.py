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
from agentsx.cli import repl
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
from agentsx.security.policy import ExecutionPolicy
from agentsx.session.store import SessionStore
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
    workspace: str = typer.Option(
        "",
        "--workspace",
        "-w",
        help="Restrict file tools to this directory",
    ),
    image: list[str] = typer.Option(
        [],
        "--image",
        "-i",
        help="Image path(s) to include in the first message",
    ),
) -> None:
    """Start an interactive chat session with an AI agent."""
    asyncio.run(
        _async_chat(
            model,
            system,
            no_tools,
            max_steps,
            allow_all,
            session,
            timeout,
            workspace,
        ),
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


def _build_user_message(
    user_input: str,
    image_paths: list[str],
) -> AgentMessage:
    """Build a user message, optionally with image content parts.

    Args:
        user_input: The user text input.
        image_paths: List of image file paths to include.

    Returns:
        An AgentMessage with multimodal content if images are provided.
    """
    from agentsx.core.types import ContentPart  # noqa: PLC0415

    if not image_paths:
        return AgentMessage(role=MessageRole.USER, content=user_input)

    parts: list[ContentPart] = []
    parts.append(ContentPart.make_text(user_input))
    for img_path in image_paths:
        parts.append(ContentPart.make_image_file(img_path))

    return AgentMessage(
        role=MessageRole.USER,
        content=user_input,
        content_parts=parts,
    )


async def _async_chat(
    model_name: str,
    system_prompt: str,
    no_tools: bool,
    max_steps: int,
    allow_all: bool = False,
    session_id: str = "",
    timeout: float = 0,
    workspace: str = "",
    image: list[str] | None = None,
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
    elif workspace:
        from pathlib import Path  # noqa: PLC0415

        policy = ExecutionPolicy.default()
        policy._allowed_dirs = [Path(workspace).resolve()]
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
    image_paths = list(image or [])

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
            new_id, new_model = repl.handle_command(
                user_input,
                messages,
                store,
                sess.id,
                shown_model,
            )
            if new_model:
                shown_model = new_model
            if new_id is not None and new_id != sess.id:
                # Session switch: reload messages
                sess = store.get(new_id)
                messages = store.get_messages(new_id)
                console.print(
                    f"[dim]Loaded session {sess.id[:12]}"
                    f" ({len(messages)} messages)[/dim]",
                )
            continue

        user_msg = _build_user_message(user_input, image_paths)
        messages.append(user_msg)
        store.append(sess.id, user_msg)
        image_paths = []

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
                repl.display_tool_event(event)
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
