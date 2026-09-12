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
async def test_usage_totals_per_source_and_task(client: AsyncClient) -> None:
    headers = await auth_header(client, email="usage@example.com")
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == "usage@example.com"))).scalar_one()
        source = Source(
            user_id=user.id,
            filename="notes.pdf",
            content_type="application/pdf",
            kind="pdf",
            storage_key="memory/usage.pdf",
            byte_size=1,
            status="ready",
            title="Usage notes",
        )
        session.add(source)
        await session.flush()
        text = "Chlorophyll captures photons for photosynthesis."
        session.add(
            DocumentChunk(
                source_id=source.id,
                user_id=user.id,
                ordinal=0,
                content=text,
                page_number=1,
                locator="p.1",
                embedding=mock_embed_vectors([text], 32)[0],
            )
        )
        source_id = str(source.id)
        await session.commit()

    gen = await client.post(f"/api/v1/sources/{source_id}/quiz/generate", headers=headers)
    assert gen.status_code == 200, gen.text

    all_usage = await client.get("/api/v1/usage", headers=headers)
    assert all_usage.status_code == 200, all_usage.text
    body = all_usage.json()
    assert body["calls"] >= 1
    assert body["total_tokens"] == body["prompt_tokens"] + body["completion_tokens"]
    assert any(row["source_id"] == source_id for row in body["by_source"])
    assert any(row["task"] == "quiz_generate" for row in body["by_task"])

    scoped = await client.get(f"/api/v1/sources/{source_id}/usage", headers=headers)
    assert scoped.status_code == 200, scoped.text
    scoped_body = scoped.json()
    assert scoped_body["calls"] >= 1
    assert scoped_body["by_source"][0]["source_id"] == source_id


@pytest.mark.asyncio
async def test_usage_is_private(client: AsyncClient) -> None:
    owner = await auth_header(client, email="usage-owner@example.com")
    other = await auth_header(client, email="usage-other@example.com")
    async with SessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.email == "usage-owner@example.com"))
        ).scalar_one()
        source = Source(
            user_id=user.id,
            filename="private.pdf",
            content_type="application/pdf",
            kind="pdf",
            storage_key="memory/private-usage.pdf",
            byte_size=1,
            status="ready",
            title="Private",
        )
        session.add(source)
        await session.commit()
        source_id = str(source.id)

    assert (await client.get(f"/api/v1/sources/{source_id}/usage", headers=other)).status_code == 404
    mine = await client.get("/api/v1/usage", headers=owner)
    assert mine.status_code == 200
