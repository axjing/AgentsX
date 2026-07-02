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

Steering queue (inspired by Pi's follow-up pattern):
    Callers can pass a mutable ``steer_queue`` (e.g. ``collections.deque``).
    Items pushed during the loop become additional user messages in the
    next turn — enabling interrupt-and-redirect without stopping the
    current tool execution.
"""

import asyncio
import logging
import time
from collections import deque
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
    StreamEvent,
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


# Maximum steer messages consumed per loop iteration (prevents unbounded
# message accumulation from a fast producer during long tool calls).
_MAX_STEER_PER_STEP = 8

# Truncation strategy: when tool output exceeds the limit, keep both the
# head and tail so the LLM sees the beginning AND the end of long results
# (e.g., the tail of a log file or the last lines of a diff).
_TRUNCATE_HEAD = 3000
_TRUNCATE_TAIL = 1000


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
    steer_queue: deque[str] | None = None,
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
        steer_queue: Optional mutable deque for interrupt-and-redirect.
            Items pushed during the loop become user messages in the next
            turn after the current step completes.

    Yields:
        ``AgentEvent`` items — ``ModelRequestEvent``, ``ModelResponseEvent``
        (delta + final), ``ToolExecutionEvent``, ``ErrorEvent``,
        ``CompactionEvent``, and ``PromptEvent``.
    """
    settings = get_settings()
    if max_steps is None:
        max_steps = settings.max_steps

    if tools is not None:
        provider.tools = tools

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

        # ── Stream from provider (with step-level timeout) ────────────
        content_parts: list[str] = []
        pending_calls: list[ToolCallStreamEvent] = []
        step_start = time.monotonic()

        step_timeout = settings.tool_timeout
        try:
            provider_stream = provider.stream_with_retry(messages)
            if step_timeout > 0:
                provider_stream = _wrap_step_timeout(provider_stream, step_timeout)
            async for event in provider_stream:
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
        except TimeoutError as te:
            yield ErrorEvent(
                error=te,
                context=f"step {step} exceeded {step_timeout}s timeout",
            )
            return
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
            yield ErrorEvent(
                error=RuntimeError(
                    f"Provider requested {len(pending_calls)} tool call(s) "
                    "but no ToolRegistry was provided",
                ),
                context="missing ToolRegistry",
            )
            return

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

        # ── Steering queue: process interrupt-and-redirect ────────────
        if steer_queue is not None:
            consumed = 0
            while steer_queue and consumed < _MAX_STEER_PER_STEP:
                steer_msg = steer_queue.popleft()
                consumed += 1
                messages.append(
                    AgentMessage(
                        role=MessageRole.USER,
                        content=steer_msg,
                    )
                )
            if steer_queue:
                logger.debug(
                    "Steer queue: consumed %d/%d items (%d remaining)",
                    consumed,
                    consumed + len(steer_queue),
                    len(steer_queue),
                )


class _Sentinel:
    pass


_STEP_DONE = _Sentinel()


async def _wrap_step_timeout(
    stream: AsyncIterator[StreamEvent],
    timeout_seconds: float,
) -> AsyncIterator[StreamEvent]:
    """Wrap a provider stream with a per-step timeout.

    Uses a sentinel value pushed to an ``asyncio.Queue`` so that the
    consumer never blocks longer than *timeout_seconds* between events,
    but finishes immediately when the source stream ends.
    """
    queue: asyncio.Queue[StreamEvent | Exception | _Sentinel] = asyncio.Queue()

    async def _drain() -> None:
        """Read from the source stream and forward to the queue."""
        try:
            async for item in stream:
                await queue.put(item)
        except Exception as exc:  # noqa: BLE001
            await queue.put(exc)
        finally:
            await queue.put(_STEP_DONE)

    asyncio.create_task(_drain())

    while True:
        try:
            item = await asyncio.wait_for(
                queue.get(),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            raise TimeoutError(  # noqa: B904
                f"Provider step timed out after {timeout_seconds}s",
            )

        if isinstance(item, _Sentinel):
            break

        if isinstance(item, Exception):
            raise item
        yield item


async def _execute_tool_with_status(
    tc: ToolCall,
    tools: ToolRegistry,
    max_output: int = 0,
) -> tuple[str, bool]:
    """Execute a single tool call and return (result_text, is_error).

    Args:
        tc: The tool call to execute.
        tools: The tool registry.
        max_output: Maximum characters to keep (0 = use resource_limits default).
            Acts as a per-call ceiling on the resource limit.
    """
    from agentsx.security.resource_limits import get_limits  # noqa: PLC0415

    try:
        result = await tools.call(tc.name, **tc.arguments)
        limits = get_limits()
        effective_limit = limits.max_output_chars
        if max_output > 0:
            effective_limit = min(max_output, effective_limit)
        if effective_limit > 0 and len(result) > effective_limit:
            result = _truncate_head_tail(result, effective_limit)
        return result, False
    except Exception as exc:  # noqa: BLE001
        return str(exc), True


def _truncate_head_tail(text: str, max_len: int) -> str:
    """Truncate long output keeping head and tail with omitted summary."""
    if max_len <= _TRUNCATE_HEAD + _TRUNCATE_TAIL:
        return f"{text[:max_len]}\n... (truncated)"

    head = text[:_TRUNCATE_HEAD]
    tail = text[-_TRUNCATE_TAIL:]
    omitted = len(text) - _TRUNCATE_HEAD - _TRUNCATE_TAIL
    return f"{head}\n\n... ({omitted:,} characters omitted) ...\n\n{tail}"
