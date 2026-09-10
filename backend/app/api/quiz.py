from __future__ import annotations

import json
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
)
from app.models.quiz import Quiz, QuizQuestion
from app.models.source import Source
from app.models.user import User
from app.services.llm.router import ModelRouter
from app.services.quiz import generate_quiz, grade_attempt

router = APIRouter(prefix="/api/v1", tags=["quiz"])


async def _owned_source(db: AsyncSession, source_id: UUID, user_id: UUID) -> Source:
    source = (await db.execute(select(Source).where(Source.id == source_id))).scalar_one_or_none()
    if source is None or source.user_id != user_id:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


def _quiz_out(quiz: Quiz, questions: list[QuizQuestion]) -> QuizOut:
    return QuizOut(
        id=quiz.id,
        source_id=quiz.source_id,
        title=quiz.title,
        questions=[
            QuizQuestionPublic(
                id=q.id,
                ordinal=q.ordinal,
                question=q.question,
                options=json.loads(q.options_json),
            )
            for q in questions
        ],
    )


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
    questions = (
        (await db.execute(select(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id).order_by(QuizQuestion.ordinal)))
        .scalars()
        .all()
    )
    return _quiz_out(quiz, list(questions))


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
    questions = (
        (await db.execute(select(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id).order_by(QuizQuestion.ordinal)))
        .scalars()
        .all()
    )
    return _quiz_out(quiz, list(questions))


@router.post("/quizzes/{quiz_id}/attempt", response_model=QuizAttemptOut)
async def attempt_quiz(
    quiz_id: UUID,
    body: QuizAttemptRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> QuizAttemptOut:
    answers = {a.question_id: a.selected_index for a in body.answers}
    try:
        attempt = await grade_attempt(db, quiz_id=quiz_id, user_id=user.id, answers=answers)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    questions = (
        (await db.execute(select(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id).order_by(QuizQuestion.ordinal)))
        .scalars()
        .all()
    )
    results: list[QuizQuestionResult] = []
    for q in questions:
        selected = answers.get(q.id, -1)
        results.append(
            QuizQuestionResult(
                question_id=q.id,
                selected_index=selected,
                correct_index=q.correct_index,
                correct=selected == q.correct_index,
                explanation=q.explanation,
                chunk_ids=json.loads(q.chunk_ids_json or "[]"),
            )
        )
    return QuizAttemptOut(
        id=attempt.id,
        quiz_id=quiz_id,
        score=attempt.score,
        passed=attempt.passed,
        results=results,
    )
