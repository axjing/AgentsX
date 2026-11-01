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
import dataclasses
import logging
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TypeAlias

from agentsx.agent.watchdog import Watchdog
from agentsx.config import AgentsXSettings, get_settings
from agentsx.context.compaction import (
    SUMMARY_END_MARKER,
    compact_messages_with_pruning,
    should_compact,
)
from agentsx.context.summarizer import ContextSummarizer
from agentsx.context.tool_pruner import prune_messages_for_compaction
from agentsx.extensions.api import (
    EVENT_ON_ERROR,
    EVENT_ON_LOOP_END,
    EVENT_ON_LOOP_START,
    EVENT_ON_MODEL_REQUEST,
    EVENT_ON_MODEL_RESPONSE,
    EVENT_ON_TOOL_CALL,
    EVENT_ON_TOOL_RESULT,
    EVENT_POST_TOOL_CALL,
    EVENT_PRE_TOOL_CALL,
    ExtensionAPI,
    ExtensionEvent,
    InterceptorEvent,
)
from agentsx.protocol.errors import (
    ClassifiedError,
    ProviderError,
    classify_api_error,
)
from agentsx.protocol.events import (
    AgentEndEvent,
    AgentEvent,
    AgentStartEvent,
    CompactionEvent,
    ErrorEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    PromptEvent,
    RetryEvent,
    StreamEvent,
    TextDeltaEvent,
    TextStreamEvent,
    ToolCallStreamEvent,
    ToolExecutionEvent,
    ToolExecutionStartEvent,
    TurnEndEvent,
    TurnStartEvent,
    UsageStreamEvent,
    WatchdogEvent,
)
from agentsx.protocol.messages import (
    AgentMessage,
    Decision,
    MessageRole,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)
from agentsx.provider import Provider
from agentsx.security.policy import ExecutionPolicy
from agentsx.security.resource_limits import get_limits
from agentsx.tools import ToolRegistry

logger = logging.getLogger(__name__)

_StreamOrRetry: TypeAlias = StreamEvent | RetryEvent
ApprovalCallback: TypeAlias = Callable[[ToolCall], Awaitable[bool]]


# Maximum steer messages consumed per loop iteration (prevents unbounded
# message accumulation from a fast producer during long tool calls).
_MAX_STEER_PER_STEP = 8


async def _compact_context(
    messages: list[AgentMessage],
    *,
    compact: bool,
    compact_max_tokens: int,
    compact_max_messages: int,
    provider: Provider | None = None,
) -> AsyncIterator[CompactionEvent]:
    """Perform context compaction if thresholds are exceeded.

    Uses LLM semantic summarization if provider is available,
    falling back to rule-based structured compaction on failure.

    Yields a ``CompactionEvent`` when compaction actually occurs.
    The caller is responsible for clearing and extending *messages*
    with the returned compacted list.
    """
    if not compact or not should_compact(
        messages,
        max_tokens=compact_max_tokens,
        max_messages=compact_max_messages,
    ):
        return

    old_count = len(messages)
    compacted: list[AgentMessage] = []

    if provider is not None:
        try:
            # Phase 1: Prune verbose tool outputs in older messages
            pruned = prune_messages_for_compaction(messages)
            # Phase 2: Attempt LLM semantic summarization
            summarizer = ContextSummarizer(max_recent=10)
            summary_res = await summarizer.summarize_with_provider(
                pruned,
                provider,
                timeout=15.0,
            )
            if summary_res.removed_count > 0 and summary_res.summary:
                header = (
                    f"[CONTEXT COMPACTION — {summary_res.removed_count} "
                    f"earlier messages compacted]\n"
                    f"{summary_res.summary}\n\n"
                    f"{SUMMARY_END_MARKER}"
                )
                compacted = summarizer.inject_summary(pruned, header)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LLM context summarization failed, falling back to rule-based: %s",
                exc,
            )
            compacted = []

    # Fallback to rule-based pruning & structured compaction
    if not compacted or len(compacted) >= old_count:
        compacted = compact_messages_with_pruning(messages)

    if len(compacted) < old_count:
        messages.clear()
        messages.extend(compacted)
        yield CompactionEvent(
            compacted_count=old_count - len(compacted),
            preserved_count=len(compacted),
        )
        logger.debug(
            "Context compacted: %d → %d messages",
            old_count,
            len(compacted),
        )


@dataclasses.dataclass
class _StreamResult:
    """Mutable container populated by _process_provider_stream."""

    content: str = ""
    tool_calls: list[ToolCallStreamEvent] = dataclasses.field(default_factory=list)
    usage: dict[str, int] = dataclasses.field(default_factory=dict)


async def _process_provider_stream(
    provider: Provider,
    messages: list[AgentMessage],
    step: int,
    settings: AgentsXSettings,
    extensions: ExtensionAPI | None,
    result: _StreamResult,
) -> AsyncIterator[AgentEvent]:
    """Stream a provider response, yielding events and populating *result*.

    Raises ``_ProviderStreamError`` on failure so the caller can
    attempt auto-retry on context overflow.
    """
    content_parts: list[str] = []
    tool_calls: list[ToolCallStreamEvent] = []
    usage_dict: dict[str, int] = {}

    provider_stream = provider.stream_with_retry(messages)
    step_timeout = settings.tool_timeout
    if step_timeout > 0:
        provider_stream = _wrap_step_timeout(provider_stream, step_timeout)

    try:
        async for event in provider_stream:
            if isinstance(event, TextStreamEvent):
                content_parts.append(event.text)
                yield TextDeltaEvent(text=event.text)
                if extensions is not None:
                    await extensions.emit(
                        ExtensionEvent(
                            type=EVENT_ON_MODEL_RESPONSE,
                            data={"content": event.text, "delta": True},
                        )
                    )
                yield ModelResponseEvent(content=event.text, delta=True)
            elif isinstance(event, ToolCallStreamEvent):
                tool_calls.append(event)
            elif isinstance(event, UsageStreamEvent):
                usage_dict = {
                    "prompt_tokens": event.prompt_tokens,
                    "completion_tokens": event.completion_tokens,
                    "total_tokens": event.total_tokens,
                    "cached_tokens": event.cached_tokens,
                }
            elif isinstance(event, RetryEvent):
                yield event
    except TimeoutError as te:
        yield ErrorEvent(
            error=te,
            context=f"step {step} exceeded {step_timeout}s timeout",
        )
        result.content = _SENTINEL_ERROR
        return
    except Exception as exc:  # noqa: BLE001
        error = exc
        if not isinstance(error, ProviderError):
            error = ProviderError(str(exc))
            error.__cause__ = exc
        classified = classify_api_error(error)
        if extensions is not None:
            await extensions.emit(
                ExtensionEvent(
                    type=EVENT_ON_ERROR,
                    data={
                        "error": str(exc),
                        "reason": str(classified.reason),
                        "recovery_hint": classified.recovery.user_hint,
                    },
                )
            )
        raise _ProviderStreamError(classified, error, exc) from exc

    result.content = "".join(content_parts)
    result.tool_calls = tool_calls
    result.usage = usage_dict


_SENTINEL_ERROR = "__STREAM_ERROR_SENTINEL__"


class _ProviderStreamError(Exception):
    """Carries classified error info from _process_provider_stream to caller."""

    def __init__(
        self,
        classified: ClassifiedError,
        error: Exception,
        original: Exception,
    ) -> None:
        super().__init__(str(original))
        self.classified = classified
        self.error = error
        self.original = original


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
    approval_callback: ApprovalCallback | None = None,
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
        approval_callback: Optional async callback invoked when a tool call
            evaluates to ``Decision.PROMPT``. If it returns True, the tool is
            executed; otherwise it is blocked.

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
    watchdog = Watchdog()

    yield AgentStartEvent(model=provider.model.id, step=0)

    while step < max_steps:
        # Wall-clock timeout check
        if timeout > 0 and (time.monotonic() - loop_start) >= timeout:
            yield ErrorEvent(
                error=TimeoutError(f"Agent loop timed out after {timeout}s"),
                context=f"timeout after {step} steps",
            )
            return

        # ── Context compaction (before each step) ─────────────────────
        async for compaction_event in _compact_context(
            messages,
            compact=compact,
            compact_max_tokens=compact_max_tokens,
            compact_max_messages=compact_max_messages,
            provider=provider,
        ):
            yield compaction_event

        step += 1
        logger.debug("Agent loop step %d", step)
        yield TurnStartEvent(turn=step)

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
        step_start = time.monotonic()
        stream_result = _StreamResult()

        try:
            async for event in _process_provider_stream(
                provider=provider,
                messages=messages,
                step=step,
                settings=settings,
                extensions=extensions,
                result=stream_result,
            ):
                yield event
        except _ProviderStreamError as pse:
            # Auto-retry on context overflow: compact and retry once
            if pse.classified.recovery.should_compress and compact:
                logger.info("Auto-compacting on context overflow")
                async for compaction_event in _compact_context(
                    messages,
                    compact=compact,
                    compact_max_tokens=compact_max_tokens,
                    compact_max_messages=compact_max_messages,
                    provider=provider,
                ):
                    yield compaction_event
                # Retry the step once after compaction
                continue

            yield ErrorEvent(
                error=pse.error,
                context=(
                    f"classified as {pse.classified.reason}: "
                    f"{pse.classified.recovery.user_hint}"
                ),
            )
            return

        if stream_result.content is _SENTINEL_ERROR:
            # Timeout already yielded ErrorEvent by _process_provider_stream
            return

        step_elapsed = time.monotonic() - step_start
        logger.debug("Step %d: provider responded in %.2fs", step, step_elapsed)

        # ── Assemble the full response ────────────────────────────────
        full_content = stream_result.content

        yield ModelResponseEvent(
            content=full_content,
            delta=False,
            step=step,
            usage=stream_result.usage or None,
        )

        # ── Append assistant message ──────────────────────────────────
        messages.append(
            AgentMessage(
                role=MessageRole.ASSISTANT,
                content=full_content,
                tool_calls=(
                    [tc.tool_call for tc in stream_result.tool_calls]
                    if stream_result.tool_calls
                    else None
                ),
            ),
        )

        # ── Tool call execution ───────────────────────────────────────
        if not stream_result.tool_calls:
            yield TurnEndEvent(turn=step, had_tool_calls=False)
            break  # no tools → loop is done

        if tools is None:
            yield ErrorEvent(
                error=RuntimeError(
                    f"Provider requested {len(stream_result.tool_calls)} tool call(s) "
                    "but no ToolRegistry was provided",
                ),
                context="missing ToolRegistry",
            )
            return

        for tc_event in stream_result.tool_calls:
            tc = tc_event.tool_call

            # ── Tool execution start ──────────────────────────────────
            yield ToolExecutionStartEvent(tool_name=tc.name, tool_call_id=tc.id)

            # ── Extension: tool call ──────────────────────────────────
            if extensions is not None:
                await extensions.emit(
                    ExtensionEvent(
                        type=EVENT_ON_TOOL_CALL,
                        data={"name": tc.name, "arguments": tc.arguments},
                    )
                )

            # ── Interceptor: pre tool call ───────────────────────────
            if extensions is not None:
                pre_event = await extensions.emit_interceptor(
                    InterceptorEvent(
                        type=EVENT_PRE_TOOL_CALL,
                        data={"name": tc.name, "arguments": tc.arguments},
                    )
                )
                if pre_event.is_suppressed:
                    tool_result = ToolResult(
                        tool_call_id=tc.id,
                        status=ToolResultStatus.BLOCKED,
                        content=f"Suppressed by extension interceptor: '{tc.name}'",
                    )
                    yield ToolExecutionEvent(
                        tool_call=tc,
                        result=tool_result,
                    )
                    messages.append(
                        AgentMessage(
                            role=MessageRole.TOOL,
                            content=tool_result.to_legacy_string(),
                            tool_call_id=tc.id,
                        ),
                    )
                    continue

            # ── Policy gate ───────────────────────────────────────────
            tool_start = time.monotonic()
            if policy is not None:
                decision = policy.evaluate(tc.name, tc.arguments)
                if decision == Decision.FORBIDDEN:
                    tool_result = ToolResult(
                        tool_call_id=tc.id,
                        status=ToolResultStatus.BLOCKED,
                        content=f"Blocked by policy: '{tc.name}' is forbidden",
                    )
                elif decision == Decision.PROMPT:
                    yield PromptEvent(
                        tool_call=tc,
                        policy_decision="requires user confirmation",
                    )
                    approved = False
                    if approval_callback is not None:
                        try:
                            approved = await approval_callback(tc)
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("Approval callback error: %s", exc)
                            approved = False

                    if approved:
                        tool_result = await _execute_tool_with_status(
                            tc,
                            tools,
                            settings.max_tool_output,
                        )
                    else:
                        tool_result = ToolResult(
                            tool_call_id=tc.id,
                            status=ToolResultStatus.BLOCKED,
                            content=(
                                f"Blocked by policy: '{tc.name}' requires "
                                "user confirmation (set policy to ALLOW to skip)"
                            ),
                        )
                else:  # ALLOW
                    tool_result = await _execute_tool_with_status(
                        tc,
                        tools,
                        settings.max_tool_output,
                    )
            else:
                tool_result = await _execute_tool_with_status(
                    tc,
                    tools,
                    settings.max_tool_output,
                )

            tool_elapsed = time.monotonic() - tool_start
            logger.debug(
                "Tool '%s' executed in %.2fs, error=%s",
                tc.name,
                tool_elapsed,
                tool_result.is_error,
            )

            result_text = tool_result.to_legacy_string()

            # ── Interceptor: post tool call ──────────────────────────
            if extensions is not None:
                post_event = await extensions.emit_interceptor(
                    InterceptorEvent(
                        type=EVENT_POST_TOOL_CALL,
                        data={
                            "name": tc.name,
                            "success": tool_result.is_success,
                            "content": result_text,
                        },
                    )
                )
                if "content" in post_event.data:
                    result_text = str(post_event.data["content"])

            # ── Extension: tool result ────────────────────────────────
            if extensions is not None:
                await extensions.emit(
                    ExtensionEvent(
                        type=EVENT_ON_TOOL_RESULT,
                        data={
                            "name": tc.name,
                            "success": tool_result.is_success,
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

            # ── Watchdog loop and failure check ───────────────────────
            warning = watchdog.record_tool_call(
                tool_name=tc.name,
                arguments=tc.arguments,
                is_error=tool_result.is_error,
            )
            if warning is not None:
                logger.warning("Watchdog triggered: %s", warning.message)
                yield WatchdogEvent(
                    warning=warning.message,
                    kind=warning.kind,
                    tool_name=warning.tool_name,
                    count=warning.count,
                )
                messages.append(
                    AgentMessage(
                        role=MessageRole.USER,
                        content=f"[System Watchdog Alert: {warning.message}]",
                    ),
                )
                if warning.circuit_broken:
                    yield ErrorEvent(
                        error=RuntimeError(
                            f"Watchdog circuit breaker tripped: {warning.message}"
                        ),
                        context=f"step {step} aborted due to unrecoverable loop",
                    )
                    return

        # ── Turn end (after tool executions) ──────────────────────────
        yield TurnEndEvent(turn=step, had_tool_calls=True)

        # ── Extension: loop end (step complete) ───────────────────────
        if extensions is not None:
            await extensions.emit(
                ExtensionEvent(
                    type=EVENT_ON_LOOP_END,
                    data={
                        "step": step,
                        "reason": "tool_calls_executed"
                        if stream_result.tool_calls
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

    reason = "completed" if step < max_steps else "max_steps"
    yield AgentEndEvent(step=step, reason=reason)


class _Sentinel:
    pass


_STEP_DONE = _Sentinel()


async def _wrap_step_timeout(
    stream: AsyncIterator[StreamEvent | RetryEvent],
    timeout_seconds: float,
) -> AsyncIterator[_StreamOrRetry]:
    """Wrap a provider stream with a per-step timeout.

    Uses a sentinel value pushed to an ``asyncio.Queue`` so that the
    consumer never blocks longer than *timeout_seconds* between events,
    but finishes immediately when the source stream ends.
    """
    queue: asyncio.Queue[_StreamOrRetry | Exception | _Sentinel] = asyncio.Queue()

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
) -> ToolResult:
    """Execute a single tool call and return a ToolResult.

    Args:
        tc: The tool call to execute.
        tools: The tool registry.
        max_output: Maximum characters to keep (0 = use resource_limits default).
            Acts as a per-call ceiling on the resource limit.
    """
    result = await tools.call(tc.name, **tc.arguments)
    if result.tool_call_id == "":
        result.tool_call_id = tc.id

    if result.is_success:
        limits = get_limits()
        effective_limit = limits.max_output_chars
        if max_output > 0:
            effective_limit = min(max_output, effective_limit)
        if effective_limit > 0 and len(result.content) > effective_limit:
            if effective_limit != limits.max_output_chars:
                trunc_limits = dataclasses.replace(
                    limits, max_output_chars=effective_limit
                )
            else:
                trunc_limits = limits
            truncated = trunc_limits.truncate_head_tail(result.content)
            result = dataclasses.replace(
                result,
                content=truncated,
                metadata={**result.metadata, "truncated": "true"},
            )
    return result
