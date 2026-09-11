from __future__ import annotations

import json
from collections import OrderedDict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.domain.schemas import (
    QuizAttemptOut,
    QuizAttemptRequest,
    QuizOut,
    QuizQuestionPublic,
    QuizQuestionResult,
    QuizRecordSummary,
    QuizRecordsOut,
    QuizSectionResult,
)
from app.models.quiz import Quiz, QuizAttempt, QuizQuestion
from app.models.source import Source
from app.models.user import User
from app.services.llm.router import ModelRouter
from app.services.quiz import generate_quiz, grade_attempt, load_details

router = APIRouter(prefix="/api/v1", tags=["quiz"])


async def _owned_source(db: AsyncSession, source_id: UUID, user_id: UUID) -> Source:
    source = (await db.execute(select(Source).where(Source.id == source_id))).scalar_one_or_none()
    if source is None or source.user_id != user_id:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


async def _questions(db: AsyncSession, quiz_id: UUID) -> list[QuizQuestion]:
    return list(
        (
            await db.execute(
                select(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id).order_by(QuizQuestion.ordinal)
            )
        )
        .scalars()
        .all()
    )


def _sections_of(questions: list[QuizQuestion]) -> list[str]:
    out: OrderedDict[str, None] = OrderedDict()
    for q in questions:
        key = q.section_title or "General"
        out[key] = None
    return list(out.keys())


def _quiz_out(quiz: Quiz, questions: list[QuizQuestion]) -> QuizOut:
    return QuizOut(
        id=quiz.id,
        source_id=quiz.source_id,
        title=quiz.title,
        prompt_version=quiz.prompt_version,
        created_at=quiz.created_at,
        sections=_sections_of(questions),
        questions=[
            QuizQuestionPublic(
                id=q.id,
                ordinal=q.ordinal,
                question=q.question,
                options=json.loads(q.options_json or "[]"),
                question_type=q.question_type,
                section_title=q.section_title,
                instructions=q.instructions,
            )
            for q in questions
        ],
    )


def _section_rollup(details: list[dict]) -> list[QuizSectionResult]:
    buckets: OrderedDict[str, dict] = OrderedDict()
    for row in details:
        key = row.get("section_title") or "General"
        bucket = buckets.setdefault(key, {"total": 0, "correct": 0, "score": 0.0})
        bucket["total"] += 1
        bucket["score"] += float(row.get("score") or 0.0)
        if row.get("correct"):
            bucket["correct"] += 1
    return [
        QuizSectionResult(
            section_title=key,
            total=b["total"],
            correct=b["correct"],
            score=round(b["score"] / b["total"], 4) if b["total"] else 0.0,
        )
        for key, b in buckets.items()
    ]


@router.post("/sources/{source_id}/quiz/generate", response_model=QuizOut)
async def api_generate_quiz(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> QuizOut:
    await _owned_source(db, source_id, user.id)
    try:
        quiz = await generate_quiz(db, source_id=source_id, user_id=user.id, router=ModelRouter(db))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _quiz_out(quiz, await _questions(db, quiz.id))


@router.get("/sources/{source_id}/quiz", response_model=QuizOut)
async def get_latest_quiz(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> QuizOut:
    await _owned_source(db, source_id, user.id)
    quiz = (
        await db.execute(
            select(Quiz)
            .where(Quiz.source_id == source_id, Quiz.user_id == user.id)
            .order_by(Quiz.created_at.desc())
        )
    ).scalars().first()
    if quiz is None:
        raise HTTPException(status_code=404, detail="No quiz yet")
    return _quiz_out(quiz, await _questions(db, quiz.id))


def _attempt_out(attempt: QuizAttempt, questions: list[QuizQuestion]) -> QuizAttemptOut:
    details = load_details(attempt)
    by_id = {str(q.id): q for q in questions}
    results: list[QuizQuestionResult] = []
    for row in details:
        q = by_id.get(str(row.get("question_id")))
        q_explanation = row.get("ai_explanation") or ""
        results.append(
            QuizQuestionResult(
                question_id=UUID(str(row["question_id"])),
                ordinal=int(row.get("ordinal") or 0),
                section_title=row.get("section_title") or "",
                question_type=row.get("question_type") or "choice",
                question=row.get("question") or (q.question if q else ""),
                selected_index=row.get("selected_index"),
                text_answer=row.get("text_answer") or "",
                correct_index=row.get("correct_index"),
                correct=bool(row.get("correct")),
                verdict=row.get("verdict") or "",
                score=row.get("score"),
                reference_answer=row.get("reference_answer") or (q.reference_answer if q else ""),
                ai_explanation=q_explanation,
                explanation=q_explanation,
                chunk_ids=[UUID(x) for x in json.loads(q.chunk_ids_json or "[]")] if q else [],
            )
        )
    return QuizAttemptOut(
        id=attempt.id,
        quiz_id=attempt.quiz_id,
        score=attempt.score,
        passed=attempt.passed,
        submitted_at=attempt.created_at,
        graded_count=attempt.graded_count,
        results=results,
        sections=_section_rollup(details),
    )


@router.post("/quizzes/{quiz_id}/attempt", response_model=QuizAttemptOut)
async def attempt_quiz(
    quiz_id: UUID,
    body: QuizAttemptRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> QuizAttemptOut:
    """Grade the submission and return a full answer sheet for every question."""
    answers = {
        a.question_id: {"selected_index": a.selected_index, "text_answer": a.text_answer or ""}
        for a in body.answers
    }
    try:
        attempt = await grade_attempt(
            db, router=ModelRouter(db), quiz_id=quiz_id, user_id=user.id, answers=answers
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _attempt_out(attempt, await _questions(db, quiz_id))


@router.get("/sources/{source_id}/quiz/records", response_model=QuizRecordsOut)
async def list_records(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> QuizRecordsOut:
    """Submission history for a source: when, what score, per-section breakdown."""
    await _owned_source(db, source_id, user.id)
    quizzes = (
        (
            await db.execute(
                select(Quiz).where(Quiz.source_id == source_id, Quiz.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    titles = {q.id: q.title for q in quizzes}
    attempts = (
        (
            await db.execute(
                select(QuizAttempt)
                .where(QuizAttempt.quiz_id.in_(titles.keys() or []), QuizAttempt.user_id == user.id)
                .order_by(QuizAttempt.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return QuizRecordsOut(
        source_id=source_id,
        records=[
            QuizRecordSummary(
                id=a.id,
                quiz_id=a.quiz_id,
                quiz_title=titles.get(a.quiz_id, "Quiz"),
                source_id=source_id,
                score=a.score,
                passed=a.passed,
                submitted_at=a.created_at,
                graded_count=a.graded_count,
                sections=_section_rollup(load_details(a)),
            )
            for a in attempts
        ],
    )


@router.get("/quiz-attempts/{attempt_id}", response_model=QuizAttemptOut)
async def get_attempt(
    attempt_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> QuizAttemptOut:
    attempt = (
        await db.execute(select(QuizAttempt).where(QuizAttempt.id == attempt_id))
    ).scalar_one_or_none()
    if attempt is None or attempt.user_id != user.id:
        raise HTTPException(status_code=404, detail="Record not found")
    return _attempt_out(attempt, await _questions(db, attempt.quiz_id))
