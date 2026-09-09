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
async def test_quiz_generate_and_attempt_mock(client: AsyncClient) -> None:
    headers = await auth_header(client, email="quiz@example.com")
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == "quiz@example.com"))).scalar_one()
        source = Source(
            user_id=user.id,
            filename="notes.pdf",
            content_type="application/pdf",
            kind="pdf",
            storage_key="memory/quiz.pdf",
            byte_size=1,
            status="ready",
            title="Notes",
        )
        session.add(source)
        await session.flush()
        text = "Photosynthesis uses chlorophyll to capture light and produce glucose."
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
    quiz = gen.json()
    assert quiz["questions"]
    # answers are hidden until submit
    assert "correct_index" not in quiz["questions"][0]

    answers = [{"question_id": q["id"], "selected_index": 0} for q in quiz["questions"]]
    attempt = await client.post(f"/api/v1/quizzes/{quiz['id']}/attempt", headers=headers, json={"answers": answers})
    assert attempt.status_code == 200, attempt.text
    body = attempt.json()
    assert 0 <= body["score"] <= 1
    assert body["results"]
    assert "correct_index" in body["results"][0]
    assert "explanation" in body["results"][0]
