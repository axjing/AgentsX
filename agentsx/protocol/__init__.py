"""Protocol types for AgentsX.

Messages, events, errors, and decision types used throughout the framework.
This is the universal data contract shared by all layers: agent loop,
providers, tools, sessions, and security.
"""

from agentsx.protocol.errors import (
    AgentsXError,
    ClassifiedError,
    FailoverReason,
    PolicyError,
    ProviderError,
    RecoveryAction,
    RetryExhaustedError,
    SessionError,
    ToolError,
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
)
from agentsx.protocol.messages import (
    AgentMessage,
    ContentPart,
    ContentType,
    Decision,
    MessageRole,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)

__all__ = [
    # Messages
    "AgentMessage",
    "ContentPart",
    "ContentType",
    "Decision",
    "MessageRole",
    "ToolCall",
    "ToolResult",
    "ToolResultStatus",
    # Events
    "AgentEndEvent",
    "AgentEvent",
    "AgentStartEvent",
    "CompactionEvent",
    "ErrorEvent",
    "ModelRequestEvent",
    "ModelResponseEvent",
    "PromptEvent",
    "RetryEvent",
    "StreamEvent",
    "TextDeltaEvent",
    "TextStreamEvent",
    "ToolCallStreamEvent",
    "ToolExecutionEvent",
    "ToolExecutionStartEvent",
    "TurnEndEvent",
    "TurnStartEvent",
    # Errors
    "AgentsXError",
    "ClassifiedError",
    "FailoverReason",
    "PolicyError",
    "ProviderError",
    "RecoveryAction",
    "RetryExhaustedError",
    "SessionError",
    "ToolError",
    "classify_api_error",
]
