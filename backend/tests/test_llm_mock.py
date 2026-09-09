from __future__ import annotations

import json
from uuid import UUID

import pytest

from app.services.llm.mock import MockProvider
from app.services.llm.base import ChatMessage
from app.utils.jsonutil import parse_json_object


@pytest.mark.asyncio
async def test_mock_llm_structured_tasks() -> None:
    provider = MockProvider()
    for task in ("summarize", "extract_knowledge", "quiz_generate", "tutor", "segment_summarize"):
        result = await provider.complete(
            task=task,
            messages=[ChatMessage(role="user", content="chunk_id=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee photosynthesis")],
            json_mode=True,
        )
        data = parse_json_object(result.content)
        assert isinstance(data, dict)
        assert result.provider == "mock"
        assert result.prompt_tokens > 0


@pytest.mark.asyncio
async def test_mock_embed_dim() -> None:
    provider = MockProvider()
    provider.dim = 32
    result = await provider.embed(task="embed", texts=["hello", "world"])
    assert len(result.vectors) == 2
    assert len(result.vectors[0]) == 32
