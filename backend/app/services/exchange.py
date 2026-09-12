from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgePoint, SourceSummary
from app.models.note import SourceNote
from app.models.quiz import Quiz, QuizAttempt, QuizQuestion
from app.models.source import Source
from app.models.tutor import TutorMessage

logger = logging.getLogger("app.exchange")

BUNDLE_FORMAT = "handbook-ai-tutor/bundle@1"
TUTOR_FORMAT = "handbook-ai-tutor/tutor@1"


def _parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


async def build_bundle(session: AsyncSession, *, source: Source, user_id: UUID) -> dict:
    summary = (
        await session.execute(select(SourceSummary).where(SourceSummary.source_id == source.id))
    ).scalar_one_or_none()
    points = (
        (
            await session.execute(
                select(KnowledgePoint)
                .where(KnowledgePoint.source_id == source.id)
                .order_by(KnowledgePoint.created_at)
            )
        )
        .scalars()
        .all()
    )
    notes = (
        (
            await session.execute(
                select(SourceNote)
                .where(SourceNote.source_id == source.id)
                .order_by(SourceNote.ordinal, SourceNote.created_at)
            )
        )
        .scalars()
        .all()
    )
    quizzes = (
        (
            await session.execute(
                select(Quiz).where(Quiz.source_id == source.id).order_by(Quiz.created_at)
            )
        )
        .scalars()
        .all()
    )

    quiz_payload: list[dict] = []
    records_payload: list[dict] = []
    for quiz in quizzes:
        questions = (
            (
                await session.execute(
                    select(QuizQuestion)
                    .where(QuizQuestion.quiz_id == quiz.id)
                    .order_by(QuizQuestion.ordinal)
                )
            )
            .scalars()
            .all()
        )
        quiz_payload.append(
            {
                "title": quiz.title,
                "prompt_version": quiz.prompt_version,
                "created_at": quiz.created_at.isoformat() if quiz.created_at else None,
                "questions": [
                    {
                        "ordinal": q.ordinal,
                        "question": q.question,
                        "question_type": q.question_type,
                        "section_title": q.section_title,
                        "options": json.loads(q.options_json or "[]"),
                        "correct_index": q.correct_index,
                        "reference_answer": q.reference_answer,
                        "rubric": q.rubric,
                        "instructions": q.instructions,
                        "explanation": q.explanation,
                    }
                    for q in questions
                ],
            }
        )
        attempts = (
            (
                await session.execute(
                    select(QuizAttempt)
                    .where(QuizAttempt.quiz_id == quiz.id, QuizAttempt.user_id == user_id)
                    .order_by(QuizAttempt.created_at)
                )
            )
            .scalars()
            .all()
        )
        for attempt in attempts:
            records_payload.append(
                {
                    "quiz_title": quiz.title,
                    "score": attempt.score,
                    "passed": attempt.passed,
                    "submitted_at": attempt.created_at.isoformat() if attempt.created_at else None,
                    "graded_count": attempt.graded_count,
                    "details": json.loads(attempt.details_json or "[]"),
                }
            )

    return {
        "format": BUNDLE_FORMAT,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "id": str(source.id),
            "filename": source.filename,
            "kind": source.kind,
            "title": source.title,
            "content_type": source.content_type,
            "byte_size": source.byte_size,
        },
        "summary": (
            {
                "title": summary.title,
                "overview": summary.overview,
                "outline": json.loads(summary.outline_json or "[]"),
                "prompt_version": summary.prompt_version,
            }
            if summary
            else None
        ),
        "knowledge": [
            {
                "title": p.title,
                "summary": p.summary,
                "key_terms": json.loads(p.key_terms_json or "[]"),
                "prompt_version": p.prompt_version,
            }
            for p in points
        ],
        "notes": [
            {
                "title": n.title,
                "content": n.content,
                "origin": n.origin,
                "anchor": n.anchor,
                "ordinal": n.ordinal,
                "created_at": n.created_at.isoformat() if n.created_at else None,
                "updated_at": n.updated_at.isoformat() if n.updated_at else None,
            }
            for n in notes
        ],
        "quizzes": quiz_payload,
        "records": records_payload,
        "tutor": await _tutor_rows(session, source_id=source.id, user_id=user_id),
    }


async def _tutor_rows(session: AsyncSession, *, source_id: UUID, user_id: UUID) -> list[dict]:
    rows = (
        (
            await session.execute(
                select(TutorMessage)
                .where(TutorMessage.source_id == source_id, TutorMessage.user_id == user_id)
                .order_by(TutorMessage.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [serialize_tutor_message(row) for row in rows]


def serialize_tutor_message(row: TutorMessage) -> dict:
    try:
        citations = json.loads(row.citations_json or "[]")
    except json.JSONDecodeError:
        citations = []
    return {
        "role": row.role,
        "content": row.content,
        "citations": citations,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def build_tutor_export(session: AsyncSession, *, source: Source, user_id: UUID) -> dict:
    return {
        "format": TUTOR_FORMAT,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "id": str(source.id),
            "filename": source.filename,
            "kind": source.kind,
            "title": source.title,
        },
        "tutor": await _tutor_rows(session, source_id=source.id, user_id=user_id),
    }


async def apply_bundle(
    session: AsyncSession,
    *,
    source: Source,
    user_id: UUID,
    bundle: dict,
    mode: str = "merge",
) -> dict:
    """Restore notes / quizzes / records from a bundle.

    mode="replace" clears the source's notes, quizzes and records first so the
    import is an exact restore. mode="merge" only adds what is missing, which is
    the safe default when merging work done on another machine.
    """
    counters = {
        "notes_created": 0,
        "notes_skipped": 0,
        "quizzes_created": 0,
        "records_created": 0,
        "summary_restored": False,
        "knowledge_restored": 0,
        "tutor_created": 0,
        "tutor_skipped": 0,
    }
    replace = mode == "replace"

    if replace:
        quiz_ids = (
            (await session.execute(select(Quiz.id).where(Quiz.source_id == source.id))).scalars().all()
        )
        if quiz_ids:
            await session.execute(delete(QuizAttempt).where(QuizAttempt.quiz_id.in_(quiz_ids)))
            await session.execute(delete(QuizQuestion).where(QuizQuestion.quiz_id.in_(quiz_ids)))
            await session.execute(delete(Quiz).where(Quiz.id.in_(quiz_ids)))
        await session.execute(delete(SourceNote).where(SourceNote.source_id == source.id))
        await session.execute(delete(KnowledgePoint).where(KnowledgePoint.source_id == source.id))
        await session.execute(delete(SourceSummary).where(SourceSummary.source_id == source.id))
        await session.execute(
            delete(TutorMessage).where(
                TutorMessage.source_id == source.id, TutorMessage.user_id == user_id
            )
        )
        await session.flush()

    # ---- summary + knowledge (only when the source has none, unless replacing)
    summary_payload = bundle.get("summary")
    if summary_payload:
        existing = (
            await session.execute(select(SourceSummary).where(SourceSummary.source_id == source.id))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                SourceSummary(
                    source_id=source.id,
                    title=str(summary_payload.get("title") or source.filename)[:255],
                    overview=str(summary_payload.get("overview") or ""),
                    outline_json=json.dumps(summary_payload.get("outline") or [], ensure_ascii=False),
                    prompt_version=str(summary_payload.get("prompt_version") or "imported"),
                )
            )
            counters["summary_restored"] = True

    existing_points = {
        (p.title, p.summary)
        for p in (
            await session.execute(select(KnowledgePoint).where(KnowledgePoint.source_id == source.id))
        )
        .scalars()
        .all()
    }
    for item in bundle.get("knowledge") or []:
        key = (str(item.get("title") or ""), str(item.get("summary") or ""))
        if key in existing_points:
            continue
        session.add(
            KnowledgePoint(
                source_id=source.id,
                title=key[0][:255],
                summary=key[1],
                key_terms_json=json.dumps(item.get("key_terms") or [], ensure_ascii=False),
                prompt_version=str(item.get("prompt_version") or "imported"),
            )
        )
        existing_points.add(key)
        counters["knowledge_restored"] += 1

    # ---- notes
    existing_notes = {
        (n.title, n.content)
        for n in (
            await session.execute(select(SourceNote).where(SourceNote.source_id == source.id))
        )
        .scalars()
        .all()
    }
    for item in bundle.get("notes") or []:
        title = str(item.get("title") or "")[:255]
        content = str(item.get("content") or "")
        if not content.strip():
            continue
        if (title, content) in existing_notes:
            counters["notes_skipped"] += 1
            continue
        note = SourceNote(
            source_id=source.id,
            user_id=user_id,
            title=title,
            content=content,
            origin=str(item.get("origin") or "imported")[:32],
            anchor=(str(item["anchor"])[:255] if item.get("anchor") else None),
            ordinal=int(item.get("ordinal") or 0),
        )
        created = _parse_dt(item.get("created_at"))
        if item.get("created_at"):
            note.created_at = created
        session.add(note)
        existing_notes.add((title, content))
        counters["notes_created"] += 1

    # ---- quizzes (match by title so records can be re-attached)
    quiz_by_title: dict[str, Quiz] = {}
    for quiz in (
        (await session.execute(select(Quiz).where(Quiz.source_id == source.id))).scalars().all()
    ):
        quiz_by_title.setdefault(quiz.title, quiz)

    for item in bundle.get("quizzes") or []:
        title = str(item.get("title") or "Imported quiz")[:255]
        if title in quiz_by_title:
            continue
        quiz = Quiz(
            source_id=source.id,
            user_id=user_id,
            title=title,
            prompt_version=str(item.get("prompt_version") or "imported")[:64],
        )
        session.add(quiz)
        await session.flush()
        for order, q in enumerate(item.get("questions") or []):
            options = q.get("options") or []
            session.add(
                QuizQuestion(
                    quiz_id=quiz.id,
                    ordinal=int(q.get("ordinal", order)),
                    question=str(q.get("question") or ""),
                    options_json=json.dumps(options, ensure_ascii=False),
                    correct_index=int(q.get("correct_index") or 0),
                    explanation=str(q.get("explanation") or ""),
                    chunk_ids_json="[]",
                    question_type=str(q.get("question_type") or "choice"),
                    section_title=str(q.get("section_title") or "")[:255],
                    reference_answer=str(q.get("reference_answer") or ""),
                    rubric=str(q.get("rubric") or ""),
                    instructions=str(q.get("instructions") or ""),
                )
            )
        quiz_by_title[title] = quiz
        counters["quizzes_created"] += 1

    # ---- records
    for item in bundle.get("records") or []:
        title = str(item.get("quiz_title") or "")
        quiz = quiz_by_title.get(title)
        if quiz is None:
            continue
        submitted = _parse_dt(item.get("submitted_at"))
        details = item.get("details") or []
        attempt = QuizAttempt(
            quiz_id=quiz.id,
            user_id=user_id,
            answers_json=json.dumps(
                [
                    {
                        "question_id": d.get("question_id"),
                        "selected_index": d.get("selected_index"),
                        "text_answer": d.get("text_answer"),
                    }
                    for d in details
                ],
                ensure_ascii=False,
            ),
            score=float(item.get("score") or 0.0),
            passed=bool(item.get("passed")),
            details_json=json.dumps(details, ensure_ascii=False),
            graded_count=int(item.get("graded_count") or 0),
        )
        if item.get("submitted_at"):
            attempt.created_at = submitted
        session.add(attempt)
        counters["records_created"] += 1

    existing_tutor = {
        (m.role, m.content)
        for m in (
            await session.execute(
                select(TutorMessage).where(
                    TutorMessage.source_id == source.id, TutorMessage.user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    }
    for item in bundle.get("tutor") or []:
        role = str(item.get("role") or "")[:32]
        content = str(item.get("content") or "")
        if role not in {"user", "assistant"} or not content.strip():
            continue
        if (role, content) in existing_tutor:
            counters["tutor_skipped"] += 1
            continue
        citations = item.get("citations") or []
        row = TutorMessage(
            source_id=source.id,
            user_id=user_id,
            role=role,
            content=content,
            citations_json=json.dumps(citations, ensure_ascii=False, default=str),
        )
        if item.get("created_at"):
            row.created_at = _parse_dt(item.get("created_at"))
        session.add(row)
        existing_tutor.add((role, content))
        counters["tutor_created"] += 1

    await session.commit()
    return counters
