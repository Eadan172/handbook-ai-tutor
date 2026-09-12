"""Deterministic coverage of the sectioned, mixed-question-type quiz flow.

The Mock provider always emits 3 sections x 4 of {choice, translation, writing,
speaking}, so this pins the behaviour that a real LLM only produces when the
source actually calls for it.
"""
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

ALLOWED_TYPES = {"choice", "translation", "writing", "speaking"}


async def _seed_source(email: str) -> str:
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        source = Source(
            user_id=user.id,
            filename="chapter.pdf",
            content_type="application/pdf",
            kind="pdf",
            storage_key="memory/chapter.pdf",
            byte_size=1,
            status="ready",
            title="Chapter book",
        )
        session.add(source)
        await session.flush()
        texts = [
            "Chapter 1 introduces photosynthesis and chlorophyll.",
            "Chapter 2 explains the light reactions and the Calvin cycle.",
            "Chapter 3 gives practice dialogues for describing a process.",
        ]
        for index, text in enumerate(texts):
            session.add(
                DocumentChunk(
                    source_id=source.id,
                    user_id=user.id,
                    ordinal=index,
                    content=text,
                    page_number=index + 1,
                    locator=f"p.{index + 1}",
                    embedding=mock_embed_vectors([text], 32)[0],
                )
            )
        source_id = str(source.id)
        await session.commit()
    return source_id


@pytest.mark.asyncio
async def test_quiz_sections_and_mixed_types(client: AsyncClient) -> None:
    headers = await auth_header(client, email="types@example.com")
    source_id = await _seed_source("types@example.com")

    gen = await client.post(f"/api/v1/sources/{source_id}/quiz/generate", headers=headers)
    assert gen.status_code == 200, gen.text
    quiz = gen.json()

    # ---- grouping
    assert len(quiz["sections"]) >= 2, quiz["sections"]
    section_titles = {q["section_title"] for q in quiz["questions"]}
    assert section_titles, "every question must carry a section_title"
    assert len(section_titles) == len(quiz["sections"]), (section_titles, quiz["sections"])

    # ---- types
    types = {q["question_type"] for q in quiz["questions"]}
    assert types <= ALLOWED_TYPES, types
    assert len(types) >= 2, f"expected mixed question types, got {types}"

    # choice questions must be locally markable
    for q in quiz["questions"]:
        if q["question_type"] == "choice":
            assert len(q["options"]) == 4, q
        else:
            assert q["options"] == [], q
            assert q["instructions"], "open-ended questions need instructions"
        assert q["instructions"] or q["question_type"] == "choice"

    # answers stay hidden before submit
    assert all("correct_index" not in q for q in quiz["questions"])

    speaking = [q for q in quiz["questions"] if q["question_type"] == "speaking"]
    assert speaking
    assert all("语音识别" in q["scoring_note"] for q in speaking)
    assert all(q["scoring_note"] == "" for q in quiz["questions"] if q["question_type"] != "speaking")


@pytest.mark.asyncio
async def test_attempt_returns_full_answer_sheet_for_every_type(client: AsyncClient) -> None:
    headers = await auth_header(client, email="sheets@example.com")
    source_id = await _seed_source("sheets@example.com")

    quiz = (await client.post(f"/api/v1/sources/{source_id}/quiz/generate", headers=headers)).json()
    questions = quiz["questions"]

    answers = [
        {"question_id": q["id"], "selected_index": 0}
        if q["question_type"] == "choice"
        else {"question_id": q["id"], "text_answer": f"my typed answer for {q['id'][:8]}"}
        for q in questions
    ]
    resp = await client.post(f"/api/v1/quizzes/{quiz['id']}/attempt", headers=headers, json={"answers": answers})
    assert resp.status_code == 200, resp.text
    attempt = resp.json()

    assert attempt["submitted_at"], "submission time must be recorded"
    assert len(attempt["results"]) == len(questions)
    assert attempt["sections"], "per-section rollup must be present"
    assert sum(s["total"] for s in attempt["sections"]) == len(questions)

    by_id = {q["id"]: q for q in questions}
    for row in attempt["results"]:
        # every single question gets an explanation, not just the wrong ones
        assert row["ai_explanation"], row
        assert row["explanation"] == row["ai_explanation"], "legacy alias must mirror"
        if row["question_type"] == "choice":
            assert row["correct_index"] is not None
            assert row["correct"] is True
            assert row["score"] == 1.0
        else:
            # open-ended: the learner's own text is echoed back verbatim
            assert row["text_answer"] == f"my typed answer for {row['question_id'][:8]}"
            assert row["verdict"], "open-ended rows need a verdict from the marking pass"
            assert row["question"] == by_id[row["question_id"]]["question"]

    # ---- records archive
    records = await client.get(f"/api/v1/sources/{source_id}/quiz/records", headers=headers)
    assert records.status_code == 200, records.text
    body = records.json()
    assert len(body["records"]) == 1
    record = body["records"][0]
    assert record["submitted_at"]
    assert record["graded_count"] == len(questions)
    assert record["sections"]

    # a stored record can be reloaded in full
    again = await client.get(f"/api/v1/quiz-attempts/{attempt['id']}", headers=headers)
    assert again.status_code == 200, again.text
    assert len(again.json()["results"]) == len(questions)


@pytest.mark.asyncio
async def test_quiz_records_are_private_to_their_owner(client: AsyncClient) -> None:
    owner = await auth_header(client, email="owner@example.com")
    source_id = await _seed_source("owner@example.com")
    quiz = (await client.post(f"/api/v1/sources/{source_id}/quiz/generate", headers=owner)).json()
    await client.post(
        f"/api/v1/quizzes/{quiz['id']}/attempt",
        headers=owner,
        json={"answers": [{"question_id": q["id"], "selected_index": 0} for q in quiz["questions"]]},
    )

    intruder = await auth_header(client, email="intruder@example.com")
    assert (await client.get(f"/api/v1/sources/{source_id}/quiz/records", headers=intruder)).status_code == 404
    assert (await client.get(f"/api/v1/sources/{source_id}/quiz", headers=intruder)).status_code == 404


@pytest.mark.asyncio
async def test_quiz_covers_each_major_section(client: AsyncClient) -> None:
    headers = await auth_header(client, email="coverage@example.com")
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == "coverage@example.com"))).scalar_one()
        source = Source(
            user_id=user.id,
            filename="book.pdf",
            content_type="application/pdf",
            kind="pdf",
            storage_key="memory/coverage.pdf",
            byte_size=1,
            status="ready",
            title="Long book",
        )
        session.add(source)
        await session.flush()
        front = ["前言", "致谢"]
        chapters = ["第1章 光反应", "第2章 暗反应", "第3章 应用", "第4章 总结"]
        ordinal = 0
        for title in front + chapters:
            for i in range(4):
                text = f"{title} body paragraph {i} about the topic in this chapter."
                session.add(
                    DocumentChunk(
                        source_id=source.id,
                        user_id=user.id,
                        ordinal=ordinal,
                        content=text,
                        page_number=ordinal + 1,
                        locator=f"p.{ordinal + 1}",
                        section_title=title,
                        content_type="body",
                        embedding=mock_embed_vectors([text], 32)[0],
                    )
                )
                ordinal += 1
        source_id = str(source.id)
        await session.commit()

    gen = await client.post(f"/api/v1/sources/{source_id}/quiz/generate", headers=headers)
    assert gen.status_code == 200, gen.text
    quiz = gen.json()
    covered = {q["section_title"] for q in quiz["questions"]}
    assert "前言" not in covered
    assert "致谢" not in covered
    assert set(chapters) <= covered, covered
