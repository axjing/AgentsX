"""Tests for security policy (``agentsx/security.py``)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from agentsx.agent.loop import run_agent_loop
from agentsx.core.types import (
    AgentMessage,
    Decision,
    MessageRole,
    StreamEvent,
    ToolCall,
    ToolCallStreamEvent,
    ToolExecutionEvent,
)
from agentsx.provider import Model, Provider
from agentsx.security import ExecutionPolicy, Rule
from agentsx.tools import ToolRegistry, ToolSpec

# ── Helpers ─────────────────────────────────────────────────


class _MockProvider(Provider):
    """Build a mock provider that yields a single ``bash`` tool call."""

    def __init__(self) -> None:
        self.model = Model(id="test", provider_name="test", max_tokens=256)
        self.tools: object = None

    async def stream(
        self,
        messages: list[AgentMessage],
    ) -> AsyncIterator[StreamEvent]:
        yield ToolCallStreamEvent(
            tool_call=ToolCall(
                id="tc1",
                name="bash",
                arguments={"command": "echo hi"},
            ),
        )

    def format_messages(
        self,
        messages: list[AgentMessage],
    ) -> list[dict[str, object]]:
        return [{"role": m.role.value, "content": m.content} for m in messages]


class _MockProvider(Provider):
    """Test provider that yields a single bash tool call."""

    def __init__(self) -> None:
        self.model = Model(id="test", provider_name="test", max_tokens=256)
        self.tools: object = None

    async def stream(
        self,
        messages: list[AgentMessage],
    ) -> AsyncIterator[StreamEvent]:
        yield ToolCallStreamEvent(
            tool_call=ToolCall(
                id="tc1",
                name="bash",
                arguments={"command": "echo hi"},
            ),
        )

    def format_messages(
        self,
        messages: list[AgentMessage],
    ) -> list[dict[str, object]]:
        return [{"role": m.role.value, "content": m.content} for m in messages]


def _mock_provider_with_tool_call() -> _MockProvider:
    """Build a mock provider that yields a single `bash` tool call."""
    return _MockProvider()


def _bash_tool_registry() -> ToolRegistry:
    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            name="bash",
            description="Run a shell command",
            fn=lambda command: "executed!",
        )
    )
    return tools


# ── Rule ─────────────────────────────────────────────────────


class TestRule:
    """Rule dataclass construction."""

    def test_basic(self) -> None:
        r = Rule("read:*", Decision.ALLOW)
        assert r.pattern == "read:*"
        assert r.decision == Decision.ALLOW


# ── ExecutionPolicy ──────────────────────────────────────────


class TestExecutionPolicy:
    """ExecutionPolicy rule matching and evaluation."""

    def test_allow_by_pattern(self) -> None:
        policy = ExecutionPolicy(rules=[Rule("read:*", Decision.ALLOW)])
        assert policy.evaluate("read", {"path": "/tmp/a.txt"}) == Decision.ALLOW

    def test_forbid_by_pattern(self) -> None:
        # Pattern matches the combined string "tool_name:{json_args}"
        # Use wildcards to match inside the JSON wrapper
        policy = ExecutionPolicy(rules=[Rule("bash:*rm*", Decision.FORBIDDEN)])
        decision = policy.evaluate("bash", {"command": "rm -rf /"})
        assert decision == Decision.FORBIDDEN

    def test_allow_other_tool_with_same_prefix(self) -> None:
        policy = ExecutionPolicy(rules=[Rule("read:*", Decision.ALLOW)])
        assert policy.evaluate("write", {"path": "/tmp/a.txt"}) == Decision.PROMPT

    def test_first_match_wins(self) -> None:
        policy = ExecutionPolicy(
            rules=[
                Rule("read:*", Decision.ALLOW),
                Rule("*", Decision.FORBIDDEN),
            ]
        )
        assert policy.evaluate("read", {"path": "x"}) == Decision.ALLOW
        assert policy.evaluate("write", {"path": "x"}) == Decision.FORBIDDEN

    def test_no_match_returns_default(self) -> None:
        policy = ExecutionPolicy(default_decision=Decision.FORBIDDEN)
        assert policy.evaluate("unknown_tool", {}) == Decision.FORBIDDEN

    def test_default_is_prompt(self) -> None:
        policy = ExecutionPolicy()
        assert policy.evaluate("any", {}) == Decision.PROMPT

    def test_empty_rules_uses_default(self) -> None:
        policy = ExecutionPolicy(rules=[])
        assert policy.evaluate("any", {}) == Decision.PROMPT

    def test_none_args(self) -> None:
        policy = ExecutionPolicy(rules=[Rule("read:*", Decision.ALLOW)])
        assert policy.evaluate("read", None) == Decision.ALLOW

    def test_default_factory_allows_reads(self) -> None:
        policy = ExecutionPolicy.default()
        assert (
            policy.evaluate("tool_file_read", {"path": "/tmp/a.txt"}) == Decision.ALLOW
        )
        assert policy.evaluate("tool_file_glob", {"pattern": "*.py"}) == Decision.ALLOW
        assert policy.evaluate("tool_file_grep", {"pattern": "foo"}) == Decision.ALLOW
        url = "https://example.com"
        assert policy.evaluate("tool_web_fetch", {"url": url}) == Decision.ALLOW
        assert policy.evaluate("tool_web_search", {"query": "test"}) == Decision.ALLOW

    def test_default_factory_prompts_mutations(self) -> None:
        policy = ExecutionPolicy.default()
        assert (
            policy.evaluate("tool_file_write", {"path": "/tmp/x.txt"})
            == Decision.PROMPT
        )
        assert (
            policy.evaluate("tool_file_edit", {"path": "/tmp/x.txt"}) == Decision.PROMPT
        )
        assert policy.evaluate("tool_bash", {"command": "ls"}) == Decision.PROMPT

    def test_default_factory_unknown_is_prompt(self) -> None:
        policy = ExecutionPolicy.default()
        assert policy.evaluate("unknown_tool", {}) == Decision.PROMPT


# ── Integration with agent loop ──────────────────────────────


class TestExecutionPolicyIntegration:
    """Policy + agent loop end-to-end."""

    @pytest.mark.asyncio
    async def test_forbidden_tool_returns_error(self) -> None:
        """A FORBIDDEN tool produces an error ToolResult."""
        provider = _mock_provider_with_tool_call()
        tools = _bash_tool_registry()
        policy = ExecutionPolicy(rules=[Rule("bash:*", Decision.FORBIDDEN)])
        messages = [AgentMessage(role=MessageRole.USER, content="run bash")]

        events: list[object] = []
        async for event in run_agent_loop(
            provider,
            messages,
            max_steps=1,
            tools=tools,
            policy=policy,
        ):
            events.append(event)

        tool_events = [e for e in events if isinstance(e, ToolExecutionEvent)]
        assert len(tool_events) == 1
        assert tool_events[0].result.is_error
        assert "forbidden" in tool_events[0].result.content.lower()

    @pytest.mark.asyncio
    async def test_allowed_tool_executes(self) -> None:
        """An ALLOWed tool executes normally."""
        provider = _mock_provider_with_tool_call()
        tools = _bash_tool_registry()
        policy = ExecutionPolicy(rules=[Rule("bash:*", Decision.ALLOW)])
        messages = [AgentMessage(role=MessageRole.USER, content="run bash")]

        events: list[object] = []
        async for event in run_agent_loop(
            provider,
            messages,
            max_steps=1,
            tools=tools,
            policy=policy,
        ):
            events.append(event)

        tool_events = [e for e in events if isinstance(e, ToolExecutionEvent)]
        assert len(tool_events) == 1
        assert not tool_events[0].result.is_error
        assert "executed" in tool_events[0].result.content

    @pytest.mark.asyncio
    async def test_no_policy_executes_unconditionally(self) -> None:
        """When policy is None, all tools execute."""
        provider = _mock_provider_with_tool_call()
        tools = _bash_tool_registry()
        messages = [AgentMessage(role=MessageRole.USER, content="run bash")]

        events: list[object] = []
        async for event in run_agent_loop(
            provider,
            messages,
            max_steps=1,
            tools=tools,
            policy=None,
        ):
            events.append(event)

        tool_events = [e for e in events if isinstance(e, ToolExecutionEvent)]
        assert len(tool_events) == 1
        assert not tool_events[0].result.is_error
