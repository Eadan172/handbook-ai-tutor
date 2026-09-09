from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.chunk import DocumentChunk
from app.models.source import Source
from app.models.user import User
from app.services.llm.mock import mock_embed_vectors
from tests.conftest import auth_header


@pytest.mark.asyncio
async def test_rag_retrieve_mock(client: AsyncClient) -> None:
    headers = await auth_header(client, email="rag@example.com")
    me = await client.get("/api/v1/auth/me", headers=headers)
    user_id = me.json()["id"]

    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == "rag@example.com"))).scalar_one()
        source = Source(
            user_id=user.id,
            filename="notes.pdf",
            content_type="application/pdf",
            kind="pdf",
            storage_key="memory/notes.pdf",
            byte_size=1,
            status="ready",
            title="Notes",
        )
        session.add(source)
        await session.flush()
        texts = [
            "Photosynthesis converts light energy into chemical energy in chloroplasts.",
            "The mitochondria is the powerhouse of the cell and produces ATP.",
        ]
        vectors = mock_embed_vectors(texts, 32)
        for i, (text, vec) in enumerate(zip(texts, vectors, strict=True)):
            session.add(
                DocumentChunk(
                    source_id=source.id,
                    user_id=user.id,
                    ordinal=i,
                    content=text,
                    page_number=i + 1,
                    locator=f"p.{i + 1}",
                    embedding=vec,
                )
            )
        source_id = str(source.id)
        await session.commit()

    resp = await client.post(
        f"/api/v1/sources/{source_id}/retrieve",
        headers=headers,
        json={"query": "How does photosynthesis capture light?", "top_k": 2},
    )
    assert resp.status_code == 200, resp.text
    citations = resp.json()["citations"]
    assert citations
    assert citations[0]["page_number"] in {1, 2}
    assert citations[0]["chunk_id"]
    assert citations[0]["source_id"] == source_id
    top = citations[0]["quote"].lower()
    assert "photosynthesis" in top or "mitochondria" in top
