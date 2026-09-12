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


@pytest.mark.asyncio
async def test_quiz_regenerate_keeps_prior_history(client: AsyncClient) -> None:
    headers = await auth_header(client, email="quiz-hist@example.com")
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == "quiz-hist@example.com"))).scalar_one()
        source = Source(
            user_id=user.id,
            filename="notes.pdf",
            content_type="application/pdf",
            kind="pdf",
            storage_key="memory/quiz-hist.pdf",
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

    first = (await client.post(f"/api/v1/sources/{source_id}/quiz/generate", headers=headers)).json()
    answers = [{"question_id": q["id"], "selected_index": 0} for q in first["questions"]]
    attempt = await client.post(
        f"/api/v1/quizzes/{first['id']}/attempt", headers=headers, json={"answers": answers}
    )
    assert attempt.status_code == 200, attempt.text

    second = await client.post(f"/api/v1/sources/{source_id}/quiz/generate", headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["id"] != first["id"]

    listed = await client.get(f"/api/v1/sources/{source_id}/quizzes", headers=headers)
    assert listed.status_code == 200, listed.text
    ids = [q["id"] for q in listed.json()["quizzes"]]
    assert first["id"] in ids
    assert second.json()["id"] in ids
    assert listed.json()["quizzes"][0]["id"] == second.json()["id"]

    latest = await client.get(f"/api/v1/sources/{source_id}/quiz", headers=headers)
    assert latest.json()["id"] == second.json()["id"]

    old = await client.get(f"/api/v1/sources/{source_id}/quiz?quiz_id={first['id']}", headers=headers)
    assert old.status_code == 200
    assert old.json()["id"] == first["id"]

    records = await client.get(f"/api/v1/sources/{source_id}/quiz/records", headers=headers)
    assert records.status_code == 200
    assert any(r["quiz_id"] == first["id"] for r in records.json()["records"])


@pytest.mark.asyncio
async def test_wrong_question_retry_grades_only_failed_items(client: AsyncClient) -> None:
    headers = await auth_header(client, email="quiz-retry@example.com")
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == "quiz-retry@example.com"))).scalar_one()
        source = Source(
            user_id=user.id,
            filename="notes.pdf",
            content_type="application/pdf",
            kind="pdf",
            storage_key="memory/quiz-retry.pdf",
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

    quiz = (await client.post(f"/api/v1/sources/{source_id}/quiz/generate", headers=headers)).json()
    choice = [q for q in quiz["questions"] if q["question_type"] == "choice"]
    assert choice, quiz["questions"]
    # First attempt: pick the wrong option on every choice question.
    answers = [
        {"question_id": q["id"], "selected_index": 1}
        if q["question_type"] == "choice"
        else {"question_id": q["id"], "text_answer": "typed"}
        for q in quiz["questions"]
    ]
    first = await client.post(
        f"/api/v1/quizzes/{quiz['id']}/attempt", headers=headers, json={"answers": answers}
    )
    assert first.status_code == 200, first.text
    failed = [r for r in first.json()["results"] if not r["correct"]]
    assert failed, first.json()["results"]
    retry_ids = [r["question_id"] for r in failed if r["question_type"] == "choice"]
    assert retry_ids

    retry = await client.post(
        f"/api/v1/quizzes/{quiz['id']}/attempt",
        headers=headers,
        json={
            "question_ids": retry_ids,
            "answers": [{"question_id": qid, "selected_index": 0} for qid in retry_ids],
        },
    )
    assert retry.status_code == 200, retry.text
    body = retry.json()
    assert len(body["results"]) == len(retry_ids)
    assert all(r["correct"] for r in body["results"])
    assert body["score"] == 1.0
    assert body["id"] != first.json()["id"]

    records = await client.get(f"/api/v1/sources/{source_id}/quiz/records", headers=headers)
    assert len(records.json()["records"]) == 2
