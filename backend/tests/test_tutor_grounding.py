from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.chunk import DocumentChunk
from app.models.source import Source
from app.models.user import User
from app.services.llm.base import LLMResult
from app.services.llm.mock import MockProvider, mock_embed_vectors
from app.services.tutor import ground_citation_ids, tutor_reply
from tests.conftest import auth_header


def test_ground_citation_ids_drops_fabricated() -> None:
    real = str(uuid4())
    fake = "00000000-0000-0000-0000-000000000099"
    assert ground_citation_ids([fake, real, fake], {real}) == [real]
    assert ground_citation_ids([fake], {real}) == []
    assert ground_citation_ids([], {real}) == []


class ScriptedRouter:
    """Returns canned tutor JSON, real embeddings via MockProvider."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.inner = MockProvider()
        self.inner.dim = 32

    async def embed(self, **kwargs):
        return await self.inner.embed(task="embed", texts=kwargs["texts"])

    async def complete(self, **kwargs):
        content = (
            self.replies.pop(0)
            if self.replies
            else json.dumps({"reply": "fallback", "citation_chunk_ids": []})
        )
        return LLMResult(
            content=content,
            prompt_tokens=1,
            completion_tokens=1,
            provider="mock",
            model="mock",
        )


@pytest.mark.asyncio
async def test_fabricated_chunk_id_does_not_survive(client: AsyncClient) -> None:
    headers = await auth_header(client, email="cite@example.com")
    fake = "00000000-0000-0000-0000-000000000099"
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == "cite@example.com"))).scalar_one()
        source = Source(
            user_id=user.id,
            filename="notes.pdf",
            content_type="application/pdf",
            kind="pdf",
            storage_key="memory/cite.pdf",
            byte_size=1,
            status="ready",
            title="Notes",
        )
        session.add(source)
        await session.flush()
        text = "Photosynthesis converts light energy into chemical energy in chloroplasts."
        chunk = DocumentChunk(
            source_id=source.id,
            user_id=user.id,
            ordinal=0,
            content=text,
            page_number=1,
            printed_page=1,
            locator="p.1",
            embedding=mock_embed_vectors([text], 32)[0],
        )
        session.add(chunk)
        await session.commit()
        source_id = source.id
        user_id = user.id
        real_id = str(chunk.id)

    router = ScriptedRouter(
        [
            json.dumps(
                {
                    "reply": "First pass cites a fabricated id.",
                    "citation_chunk_ids": [real_id, fake],
                }
            ),
            json.dumps(
                {
                    "reply": "Retry still mentions the fake id.",
                    "citation_chunk_ids": [fake],
                }
            ),
        ]
    )
    async with SessionLocal() as session:
        row = await tutor_reply(
            session,
            source_id=source_id,
            user_id=user_id,
            message="What is photosynthesis?",
            router=router,  # type: ignore[arg-type]
        )
        citations = json.loads(row.citations_json or "[]")

    ids = [str(c["chunk_id"]) for c in citations]
    assert fake not in ids
    assert all(cid != fake for cid in ids)


@pytest.mark.asyncio
async def test_tutor_chat_only_returns_retrieved_ids(client: AsyncClient) -> None:
    headers = await auth_header(client, email="tutorapi@example.com")
    async with SessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.email == "tutorapi@example.com"))
        ).scalar_one()
        source = Source(
            user_id=user.id,
            filename="notes.pdf",
            content_type="application/pdf",
            kind="pdf",
            storage_key="memory/tutor.pdf",
            byte_size=1,
            status="ready",
            title="Notes",
        )
        session.add(source)
        await session.flush()
        text = "The Calvin cycle fixes carbon dioxide into glucose."
        session.add(
            DocumentChunk(
                source_id=source.id,
                user_id=user.id,
                ordinal=0,
                content=text,
                page_number=12,
                printed_page=12,
                locator="p.12",
                embedding=mock_embed_vectors([text], 32)[0],
            )
        )
        source_id = str(source.id)
        await session.commit()

    resp = await client.post(
        f"/api/v1/sources/{source_id}/tutor/chat",
        headers=headers,
        json={"message": "What happens in the Calvin cycle?"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "assistant"
    for citation in body["citations"]:
        UUID(citation["chunk_id"])
        assert citation["source_id"] == source_id
