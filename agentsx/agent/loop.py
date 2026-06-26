"""Pure-function agent loop (ReAct pattern).

``run_agent_loop()`` is the single entry point.  It drives a
think → act → observe → repeat cycle:

1. Send accumulated messages to the LLM provider.
2. Stream the text response, yielding ``ModelResponseEvent`` deltas.
3. When the provider emits ``ToolCallStreamEvent`` items, evaluate
   each against the optional ``ExecutionPolicy`` gate, then execute
   via ``ToolRegistry``, yielding ``ToolExecutionEvent``.
4. After *max_steps* iterations (or when no tool call is requested)
   yield a terminal ``ModelResponseEvent`` and return.

Automatic context compaction is triggered when the message list
exceeds configured thresholds (based on Pi's design).
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator

from agentsx.config import get_settings
from agentsx.context.compaction import compact_messages, should_compact
from agentsx.core.types import (
    AgentEvent,
    AgentMessage,
    CompactionEvent,
    Decision,
    ErrorEvent,
    MessageRole,
    ModelRequestEvent,
    ModelResponseEvent,
    PromptEvent,
    TextStreamEvent,
    ToolCall,
    ToolCallStreamEvent,
    ToolExecutionEvent,
    ToolResult,
)
from agentsx.extensions.api import (
    EVENT_ON_ERROR,
    EVENT_ON_LOOP_END,
    EVENT_ON_LOOP_START,
    EVENT_ON_MODEL_REQUEST,
    EVENT_ON_MODEL_RESPONSE,
    EVENT_ON_TOOL_CALL,
    EVENT_ON_TOOL_RESULT,
    ExtensionAPI,
    ExtensionEvent,
)
from agentsx.provider import Provider
from agentsx.security.policy import ExecutionPolicy
from agentsx.tools import ToolRegistry

logger = logging.getLogger(__name__)


async def run_agent_loop(
    provider: Provider,
    messages: list[AgentMessage],
    max_steps: int | None = None,
    tools: ToolRegistry | None = None,
    policy: ExecutionPolicy | None = None,
    extensions: ExtensionAPI | None = None,
    timeout: float = 0,
    compact: bool = True,
    compact_max_tokens: int = 0,
    compact_max_messages: int = 50,
) -> AsyncIterator[AgentEvent]:
    """Run the ReAct agent loop.

    Args:
        provider: An LLM provider instance.
        messages: Conversation history (modified in-place as the loop
            progresses).  May be compacted in-place when *compact* is True.
        max_steps: Maximum tool-calling iterations.  Falls back to
            ``AGENTSX_MAX_STEPS`` when *None*.
        tools: Optional ToolRegistry.  When provided, tool call requests
            from the LLM are executed and their results fed back into the loop.
        policy: Optional security policy.  When provided, tool calls
            are evaluated against rules before execution.
        extensions: Optional extension API for lifecycle hooks.
        timeout: Wall-clock timeout in seconds for the entire loop.
            0 (default) means no timeout.
        compact: Enable automatic context compaction.
        compact_max_tokens: Token budget before compaction (0 = use message
            count only).
        compact_max_messages: Maximum message count before compaction.

    Yields:
        ``AgentEvent`` items — ``ModelRequestEvent``, ``ModelResponseEvent``
        (delta + final), ``ToolExecutionEvent``, ``ErrorEvent``,
        ``CompactionEvent``, and ``PromptEvent``.
    """
    settings = get_settings()
    if max_steps is None:
        max_steps = settings.max_steps

    step = 0
    loop_start = time.monotonic()

    while step < max_steps:
        # Wall-clock timeout check
        if timeout > 0 and (time.monotonic() - loop_start) >= timeout:
            yield ErrorEvent(
                error=TimeoutError(f"Agent loop timed out after {timeout}s"),
                context=f"timeout after {step} steps",
            )
            return

        # ── Context compaction (before each step) ─────────────────────
        if compact and should_compact(
            messages,
            max_tokens=compact_max_tokens,
            max_messages=compact_max_messages,
        ):
            old_count = len(messages)
            compacted = compact_messages(messages)
            if len(compacted) < old_count:
                compacted_count = old_count - len(compacted)
                messages.clear()
                messages.extend(compacted)
                yield CompactionEvent(
                    compacted_count=compacted_count,
                    preserved_count=len(compacted),
                )
                logger.debug(
                    "Context compacted: %d → %d messages",
                    old_count,
                    len(compacted),
                )

        step += 1
        logger.debug("Agent loop step %d", step)

        # ── Extension: loop start ─────────────────────────────────────
        if extensions is not None:
            await extensions.emit(
                ExtensionEvent(
                    type=EVENT_ON_LOOP_START,
                    data={"step": step},
                )
            )

        # ── Signal request to provider ────────────────────────────────
        if extensions is not None:
            await extensions.emit(
                ExtensionEvent(
                    type=EVENT_ON_MODEL_REQUEST,
                    data={"model": provider.model.id},
                )
            )
        yield ModelRequestEvent(
            messages=list(messages),
            model=provider.model.id,
        )

        # ── Stream from provider (with retry) ─────────────────────────
        content_parts: list[str] = []
        pending_calls: list[ToolCallStreamEvent] = []
        step_start = time.monotonic()

        provider.tools = tools
        try:
            async for event in provider.stream_with_retry(messages):
                if isinstance(event, TextStreamEvent):
                    content_parts.append(event.text)
                    if extensions is not None:
                        await extensions.emit(
                            ExtensionEvent(
                                type=EVENT_ON_MODEL_RESPONSE,
                                data={"content": event.text, "delta": True},
                            )
                        )
                    yield ModelResponseEvent(content=event.text, delta=True)
                elif isinstance(event, ToolCallStreamEvent):
                    pending_calls.append(event)
        except Exception as exc:  # noqa: BLE001
            if extensions is not None:
                await extensions.emit(
                    ExtensionEvent(
                        type=EVENT_ON_ERROR,
                        data={
                            "error": str(exc),
                            "context": f"stream failed at step {step}",
                        },
                    )
                )
            yield ErrorEvent(
                error=exc,
                context=f"Provider stream failed at step {step}",
            )
            return

        step_elapsed = time.monotonic() - step_start
        logger.debug("Step %d: provider responded in %.2fs", step, step_elapsed)

        # ── Assemble the full response ────────────────────────────────
        full_content = "".join(content_parts)

        yield ModelResponseEvent(
            content=full_content,
            delta=False,
            step=step,
        )

        # ── Append assistant message ──────────────────────────────────
        messages.append(
            AgentMessage(
                role=MessageRole.ASSISTANT,
                content=full_content,
                tool_calls=(
                    [tc.tool_call for tc in pending_calls] if pending_calls else None
                ),
            ),
        )

        # ── Tool call execution ───────────────────────────────────────
        if not pending_calls:
            break  # no tools → loop is done

        if tools is None:
            raise RuntimeError(
                f"Provider requested {len(pending_calls)} tool call(s) "
                "but no ToolRegistry was provided",
            )

        for tc_event in pending_calls:
            tc = tc_event.tool_call

            # ── Extension: tool call ──────────────────────────────────
            if extensions is not None:
                await extensions.emit(
                    ExtensionEvent(
                        type=EVENT_ON_TOOL_CALL,
                        data={"name": tc.name, "arguments": tc.arguments},
                    )
                )

            # ── Policy gate ───────────────────────────────────────────
            tool_start = time.monotonic()
            if policy is not None:
                decision = policy.evaluate(tc.name, tc.arguments)
                if decision == Decision.FORBIDDEN:
                    result_text = f"Blocked by policy: '{tc.name}' is forbidden"
                    error_flag = True
                elif decision == Decision.PROMPT:
                    yield PromptEvent(
                        tool_call=tc,
                        policy_decision="requires user confirmation",
                    )
                    result_text = (
                        f"Blocked by policy: '{tc.name}' requires "
                        "user confirmation (set policy to ALLOW to skip)"
                    )
                    error_flag = True
                else:  # ALLOW
                    result_text, error_flag = await _execute_tool_with_status(
                        tc,
                        tools,
                        settings.max_tool_output,
                    )
            else:
                result_text, error_flag = await _execute_tool_with_status(
                    tc,
                    tools,
                    settings.max_tool_output,
                )

            tool_elapsed = time.monotonic() - tool_start
            logger.debug(
                "Tool '%s' executed in %.2fs, error=%s",
                tc.name,
                tool_elapsed,
                error_flag,
            )

            tool_result = ToolResult(
                id=f"tr_{tc.id}",
                tool_call_id=tc.id,
                content=result_text,
                is_error=error_flag,
            )

            # ── Extension: tool result ────────────────────────────────
            if extensions is not None:
                await extensions.emit(
                    ExtensionEvent(
                        type=EVENT_ON_TOOL_RESULT,
                        data={
                            "name": tc.name,
                            "success": not error_flag,
                            "content": result_text[:500],
                        },
                    )
                )

            yield ToolExecutionEvent(
                tool_call=tc,
                result=tool_result,
            )

            messages.append(
                AgentMessage(
                    role=MessageRole.TOOL,
                    content=result_text,
                    tool_call_id=tc.id,
                ),
            )

        # ── Extension: loop end (step complete) ───────────────────────
        if extensions is not None:
            await extensions.emit(
                ExtensionEvent(
                    type=EVENT_ON_LOOP_END,
                    data={
                        "step": step,
                        "reason": "tool_calls_executed"
                        if pending_calls
                        else "completed",
                    },
                )
            )


async def _execute_tool_with_status(
    tc: ToolCall,
    tools: ToolRegistry,
    max_output: int = 0,
) -> tuple[str, bool]:
    """Execute a single tool call and return (result_text, is_error).

    Args:
        tc: The tool call to execute.
        tools: The tool registry.
        max_output: Maximum characters to keep (0 = no limit).
    """
    try:
        result = await tools.call(tc.name, **tc.arguments)
        if max_output > 0 and len(result) > max_output:
            truncated = result[:max_output]
            result = f"{truncated}\n... (output truncated at {max_output} chars)"
        return result, False
    except Exception as exc:  # noqa: BLE001
        return str(exc), True
