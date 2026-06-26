import asyncio

from agentsx.agent.loop import run_agent_loop
from agentsx.core.types import (
    AgentMessage,
    ErrorEvent,
    MessageRole,
    ModelResponseEvent,
)
from agentsx.provider import create_provider
from agentsx.security.policy import ExecutionPolicy
from agentsx.tools import ToolRegistry
from agentsx.tools.builtin import ALL_TOOLS


async def main():
    provider = create_provider(
        model_name="gpt-4o",
        api_key="sk-5PQREuaqS3g8ybOdfVC5xJE223OMVKDBWbg1nx2pT6LtxWNc",
        api_base="https://lonlie.plus7.plus/v1",
    )
    tools = ToolRegistry()
    tools.register_all(*ALL_TOOLS)

    messages = [
        AgentMessage(role=MessageRole.SYSTEM, content="You are a helpful assistant."),
        AgentMessage(
            role=MessageRole.USER,
            content="Read the file README.md and summarize it",
        ),
    ]

    async for event in run_agent_loop(
        provider,
        messages,
        tools=tools,
        policy=ExecutionPolicy.default(),
    ):
        if isinstance(event, ModelResponseEvent):
            print(event.content, end="")
        elif isinstance(event, ErrorEvent):
            print(f"[ERROR] {event.error}")
        else:
            print(event)


asyncio.run(main())
