from __future__ import annotations

import json
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import DocumentChunk
from app.models.quiz import Quiz, QuizAttempt, QuizQuestion
from app.prompts import load_prompt
from app.services.chunking import format_excerpts
from app.services.llm.base import ChatMessage
from app.services.llm.router import ModelRouter
from app.utils.jsonutil import parse_model


class QuizQuestionSchema(BaseModel):
    question: str
    options: list[str]
    correct_index: int
    explanation: str = ""
    chunk_ids: list[str] = Field(default_factory=list)


class QuizSchema(BaseModel):
    title: str
    questions: list[QuizQuestionSchema]


async def generate_quiz(
    session: AsyncSession,
    *,
    source_id: UUID,
    user_id: UUID,
    router: ModelRouter,
) -> Quiz:
    chunks = (
        (
            await session.execute(
                select(DocumentChunk)
                .where(DocumentChunk.source_id == source_id)
                .order_by(DocumentChunk.ordinal)
            )
        )
        .scalars()
        .all()
    )
    if not chunks:
        raise ValueError("Source has no chunks yet; wait for ingest to finish.")
    known = {str(c.id) for c in chunks}
    excerpts = format_excerpts(chunks, max_chars=7000)
    result = await router.complete(
        task="quiz_generate",
        messages=[
            ChatMessage(role="system", content=load_prompt("quiz_generate.v1.txt")),
            ChatMessage(role="user", content=excerpts),
        ],
        user_id=user_id,
        source_id=source_id,
    )
    parsed = parse_model(result.content, QuizSchema)
    quiz = Quiz(source_id=source_id, user_id=user_id, title=parsed.title, prompt_version="quiz_generate.v1")
    session.add(quiz)
    await session.flush()
    for i, q in enumerate(parsed.questions):
        options = q.options[:4] + ["(blank)"] * max(0, 4 - len(q.options))
        correct = q.correct_index if 0 <= q.correct_index < 4 else 0
        ids = [c for c in q.chunk_ids if c in known]
        session.add(
            QuizQuestion(
                quiz_id=quiz.id,
                ordinal=i,
                question=q.question,
                options_json=json.dumps(options[:4], ensure_ascii=False),
                correct_index=correct,
                explanation=q.explanation,
                chunk_ids_json=json.dumps(ids),
            )
        )
    await session.commit()
    await session.refresh(quiz)
    return quiz


async def grade_attempt(
    session: AsyncSession,
    *,
    quiz_id: UUID,
    user_id: UUID,
    answers: dict[UUID, int],
) -> QuizAttempt:
    quiz = (await session.execute(select(Quiz).where(Quiz.id == quiz_id))).scalar_one_or_none()
    if quiz is None or quiz.user_id != user_id:
        raise ValueError("Quiz not found")
    questions = (
        (await session.execute(select(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id).order_by(QuizQuestion.ordinal)))
        .scalars()
        .all()
    )
    correct = 0
    payload = []
    for q in questions:
        selected = answers.get(q.id, -1)
        is_correct = selected == q.correct_index
        if is_correct:
            correct += 1
        payload.append({"question_id": str(q.id), "selected_index": selected})
    score = (correct / len(questions)) if questions else 0.0
    attempt = QuizAttempt(
        quiz_id=quiz_id,
        user_id=user_id,
        answers_json=json.dumps(payload),
        score=score,
        passed=score >= 0.6,
    )
    session.add(attempt)
    await session.commit()
    await session.refresh(attempt)
    return attempt
