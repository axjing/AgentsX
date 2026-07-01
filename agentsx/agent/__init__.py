"""Agent loop and state management.

The core of the framework: ``run_agent_loop()`` is a pure async generator
that yields ``AgentEvent`` items.  The ``Agent`` class wraps the loop for
convenient single-call usage.
"""

from agentsx.agent.agent import Agent
from agentsx.agent.loop import run_agent_loop

__all__ = [
    "Agent",
    "run_agent_loop",
]
