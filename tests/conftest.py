"""Global test configuration and fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from agentsx.core.types import AgentMessage, TextStreamEvent
from agentsx.provider import Model, Provider


@pytest.fixture
def mock_provider() -> Provider:
    """Create a mock provider that echoes input as response."""
    provider = AsyncMock(spec=Provider)
    provider.model = Model(id="test-model", provider_name="test", max_tokens=4096)

    async def stream(
        messages: list[AgentMessage],
    ) -> AsyncIterator[TextStreamEvent]:
        for m in messages:
            yield TextStreamEvent(text=str(m.content))

    provider.stream = stream
    provider.format_messages = lambda msgs: [
        {"role": m.role.value, "content": m.content} for m in msgs
    ]
    return provider
