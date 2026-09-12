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


async def _ready_source(email: str) -> str:
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        source = Source(
            user_id=user.id,
            filename="notes.pdf",
            content_type="application/pdf",
            kind="pdf",
            storage_key="memory/tutor-export.pdf",
            byte_size=1,
            status="ready",
            title="Notes",
        )
        session.add(source)
        await session.flush()
        text = "指令级并行（ILP）通过在一个时钟周期内发射多条指令提高吞吐。"
        session.add(
            DocumentChunk(
                source_id=source.id,
                user_id=user.id,
                ordinal=0,
                content=text,
                page_number=12,
                printed_page=12,
                locator="书内 p.12",
                embedding=mock_embed_vectors([text], 32)[0],
            )
        )
        source_id = str(source.id)
        await session.commit()
    return source_id


@pytest.mark.asyncio
async def test_tutor_export_and_import_roundtrip(client: AsyncClient) -> None:
    headers = await auth_header(client, email="tutor-io@example.com")
    source_id = await _ready_source("tutor-io@example.com")

    chat = await client.post(
        f"/api/v1/sources/{source_id}/tutor/chat",
        headers=headers,
        json={"message": "什么是指令级并行？"},
    )
    assert chat.status_code == 200, chat.text

    exported = await client.get(f"/api/v1/sources/{source_id}/tutor/export", headers=headers)
    assert exported.status_code == 200, exported.text
    payload = exported.json()
    assert payload["format"] == "handbook-ai-tutor/tutor@1"
    assert payload["tutor"]
    assert any(row["role"] == "user" for row in payload["tutor"])
    assert any(row["role"] == "assistant" for row in payload["tutor"])

    imported = await client.post(
        f"/api/v1/sources/{source_id}/tutor/import",
        headers=headers,
        json={"bundle": payload, "mode": "merge"},
    )
    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert body["tutor_skipped"] >= 1
    assert body["tutor_created"] == 0

    payload["tutor"].append(
        {
            "role": "user",
            "content": "再解释一下流水线冒险。",
            "citations": [],
            "created_at": payload["exported_at"],
        }
    )
    again = await client.post(
        f"/api/v1/sources/{source_id}/tutor/import",
        headers=headers,
        json={"bundle": payload, "mode": "merge"},
    )
    assert again.status_code == 200, again.text
    assert again.json()["tutor_created"] == 1

    history = await client.get(f"/api/v1/sources/{source_id}/tutor/messages", headers=headers)
    assert history.status_code == 200
    contents = [row["content"] for row in history.json()]
    assert "再解释一下流水线冒险。" in contents


@pytest.mark.asyncio
async def test_tutor_chat_failed_source_is_chinese(client: AsyncClient) -> None:
    headers = await auth_header(client, email="tutor-fail@example.com")
    async with SessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.email == "tutor-fail@example.com"))
        ).scalar_one()
        source = Source(
            user_id=user.id,
            filename="book.pdf",
            content_type="application/pdf",
            kind="pdf",
            storage_key="memory/failed.pdf",
            byte_size=1,
            status="failed",
            error_message="embed routing exploded",
            title="Broken",
        )
        session.add(source)
        await session.flush()
        source_id = str(source.id)
        await session.commit()

    resp = await client.post(
        f"/api/v1/sources/{source_id}/tutor/chat",
        headers=headers,
        json={"message": "hello"},
    )
    assert resp.status_code == 409
    assert "解析失败" in resp.json()["detail"]
