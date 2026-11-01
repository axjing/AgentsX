"""Agent loop and state management.

The core of the framework: ``run_agent_loop()`` is a pure async generator
that yields ``AgentEvent`` items.  The ``Agent`` class wraps the loop for
convenient single-call usage.
"""

from agentsx.agent.agent import Agent
from agentsx.agent.crystallizer import AutonomousCrystallizer, CrystallizedRule
from agentsx.agent.loop import ApprovalCallback, run_agent_loop
from agentsx.agent.verifier import ProactiveQualityGate, QualityCheckResult

__all__ = [
    "Agent",
    "ApprovalCallback",
    "AutonomousCrystallizer",
    "CrystallizedRule",
    "ProactiveQualityGate",
    "QualityCheckResult",
    "run_agent_loop",
]
