from __future__ import annotations

import json
import logging
from collections import OrderedDict
from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import DocumentChunk
from app.models.quiz import QUESTION_TYPES, Quiz, QuizAttempt, QuizQuestion
from app.prompts import load_prompt
from app.services.chunking import format_document_excerpts
from app.services.llm.base import ChatMessage
from app.services.llm.router import ModelRouter
from app.utils.jsonutil import parse_json_object

logger = logging.getLogger("app.quiz")

QUIZ_PROMPT_VERSION = "quiz_generate.v2"
EXPLAIN_PROMPT_VERSION = "quiz_explain.v1"

# Per-section generate + merge only when the document is large enough that a
# single 11k excerpt would still under-represent later chapters.
_SECTION_GENERATE_MIN = 4
_SECTION_GENERATE_CHUNK_MIN = 16
_MAX_SECTIONS = 8
_PER_SECTION_KEEP = 2

SPEAKING_SCORING_NOTE = (
    "口语按你输入的文本对照参考答案与评分细则批改，未做语音识别。"
)


# ---------------------------------------------------------------- generation


class QuizQuestionSchema(BaseModel):
    section_title: str = ""
    question_type: str = "choice"
    question: str
    options: list[str] = Field(default_factory=list)
    correct_index: int = 0
    reference_answer: str = ""
    rubric: str = ""
    instructions: str = ""
    explanation: str = ""
    chunk_ids: list[str] = Field(default_factory=list)


class QuizSchema(BaseModel):
    title: str
    questions: list[QuizQuestionSchema]


def _normalise_type(raw: str, options: list[str]) -> str:
    value = (raw or "").strip().lower()
    if value not in QUESTION_TYPES:
        # A question carrying options is a choice question whatever the label said.
        value = "choice" if options else "writing"
    return value


def major_sections(chunks: list) -> list[str]:
    """Document section titles in reading order, skipping empty / outline-only."""
    seen: OrderedDict[str, None] = OrderedDict()
    for chunk in chunks:
        title = (getattr(chunk, "section_title", None) or "").strip()
        kind = getattr(chunk, "content_type", "") or ""
        if title and kind != "outline":
            seen[title] = None
    return list(seen)


def scoring_note_for(question_type: str) -> str:
    return SPEAKING_SCORING_NOTE if question_type == "speaking" else ""


async def _complete_quiz(router: ModelRouter, user_id: UUID, source_id: UUID, user_content: str):
    return await router.complete(
        task="quiz_generate",
        messages=[
            ChatMessage(role="system", content=load_prompt("quiz_generate.v2.txt")),
            ChatMessage(role="user", content=user_content),
        ],
        user_id=user_id,
        source_id=source_id,
    )


async def _generate_per_section(
    chunks: list,
    *,
    router: ModelRouter,
    user_id: UUID,
    source_id: UUID,
    sections: list[str],
) -> tuple[str, list]:
    """One generate call per major section, then merge.

    Keeps the token budget per call small and guarantees later chapters appear.
    """
    outline = [c for c in chunks if (getattr(c, "content_type", "") or "") == "outline"]
    collected: list = []
    title = "Practice quiz"
    for index, section in enumerate(sections[:_MAX_SECTIONS]):
        scoped = outline + [
            c for c in chunks if (getattr(c, "section_title", None) or "").strip() == section
        ]
        excerpts = format_document_excerpts(scoped or chunks, max_chars=3500)
        user = (
            f"Generate at most {_PER_SECTION_KEEP} questions ONLY for this section: "
            f"{section}\nCover this section; do not invent other chapters.\n\n{excerpts}"
        )
        result = await _complete_quiz(router, user_id, source_id, user)
        data = parse_json_object(result.content)
        if index == 0 and data.get("title"):
            title = str(data.get("title") or title)
        kept = 0
        for raw in data.get("questions") or []:
            if not isinstance(raw, dict):
                continue
            raw["section_title"] = str(raw.get("section_title") or section)
            collected.append(raw)
            kept += 1
            if kept >= _PER_SECTION_KEEP:
                break
    return title, collected


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
    # Structure-first sampling: a quiz that only ever sees the preface cannot be
    # "chapter by chapter", which is what the learner asked for.
    sections = major_sections(chunks)
    if len(sections) >= _SECTION_GENERATE_MIN and len(chunks) >= _SECTION_GENERATE_CHUNK_MIN:
        title, questions = await _generate_per_section(
            chunks, router=router, user_id=user_id, source_id=source_id, sections=sections
        )
    else:
        excerpts = format_document_excerpts(chunks, max_chars=11000)
        result = await _complete_quiz(router, user_id, source_id, excerpts)
        data = parse_json_object(result.content)
        title = str(data.get("title") or "Practice quiz")
        questions = data.get("questions") or []

    # Always INSERT a new Quiz row. Prior quizzes and their attempts stay so
    # regenerate does not wipe history. The GET latest endpoint returns this one.
    quiz = Quiz(
        source_id=source_id,
        user_id=user_id,
        title=title,
        prompt_version=QUIZ_PROMPT_VERSION,
        created_at=datetime.now(timezone.utc),
    )
    session.add(quiz)
    await session.flush()

    ordinal = 0
    for raw in questions:
        try:
            q = QuizQuestionSchema.model_validate(raw)
        except Exception:
            continue
        options = [str(o) for o in q.options][:4]
        qtype = _normalise_type(q.question_type, options)
        if qtype == "choice":
            options = options + ["(blank)"] * max(0, 4 - len(options))
        else:
            options = []
        correct = q.correct_index if 0 <= q.correct_index < max(1, len(options)) else 0
        ids = [c for c in q.chunk_ids if c in known]
        session.add(
            QuizQuestion(
                quiz_id=quiz.id,
                ordinal=ordinal,
                question=q.question,
                options_json=json.dumps(options, ensure_ascii=False),
                correct_index=correct,
                explanation=q.explanation,
                chunk_ids_json=json.dumps(ids),
                question_type=qtype,
                section_title=q.section_title or "",
                reference_answer=q.reference_answer,
                rubric=q.rubric,
                instructions=q.instructions,
            )
        )
        ordinal += 1

    if ordinal == 0:
        await session.rollback()
        raise ValueError("The model returned no questions; try again or check your LLM provider.")

    await session.commit()
    await session.refresh(quiz)
    return quiz


# ------------------------------------------------------------------- grading


class ExplainItem(BaseModel):
    ordinal: int
    verdict: str = ""
    score: float | None = None
    explanation: str = ""


class ExplainSchema(BaseModel):
    results: list[ExplainItem]


def _fallback_explanation(q: QuizQuestion, correct: bool, user_answer: str) -> str:
    """Deterministic explanation used when the explain pass cannot run."""
    if q.question_type == "choice":
        try:
            options = json.loads(q.options_json or "[]")
        except json.JSONDecodeError:
            options = []
        right = options[q.correct_index] if 0 <= q.correct_index < len(options) else "-"
        if correct:
            return f"Correct. The source supports: {right}"
        return f"Not quite. The correct option is: {right}"
    if not user_answer.strip():
        return "No answer was submitted. Compare with the reference answer shown above and try again."
    return (
        "Automatic explanation unavailable (the marking model could not be reached). "
        "Compare your answer with the reference answer above."
    )


def _build_explain_prompt(rows: list[dict]) -> str:
    parts: list[str] = []
    for row in rows:
        lines = [
            f"ordinal={row['ordinal']}",
            f"section: {row['section_title'] or '-'}",
            f"type: {row['question_type']}",
            f"question: {row['question']}",
        ]
        if row["question_type"] == "choice":
            options = row["options"]
            lines.append("options: " + " | ".join(f"{i}. {o}" for i, o in enumerate(options)))
            lines.append(f"correct_index: {row['correct_index']}")
        if row["reference_answer"]:
            lines.append(f"reference_answer: {row['reference_answer']}")
        if row["rubric"]:
            lines.append(f"rubric: {row['rubric']}")
        lines.append(f"learner_answer: {row['user_answer'] or '(empty)'}")
        parts.append("\n".join(lines))
    return "\n\n---\n\n".join(parts)


def _score_for(result: dict) -> float:
    raw = result.get("score")
    if isinstance(raw, (int, float)):
        return max(0.0, min(1.0, float(raw)))
    verdict = str(result.get("verdict") or "").lower()
    if verdict == "correct":
        return 1.0
    if verdict == "partially_correct":
        return 0.5
    return 0.0


async def grade_attempt(
    session: AsyncSession,
    *,
    router: ModelRouter,
    quiz_id: UUID,
    user_id: UUID,
    answers: dict[UUID, dict],
    question_ids: list[UUID] | None = None,
) -> QuizAttempt:
    """Grade every question, then explain every question.

    `answers` maps question_id -> {"selected_index": int | None, "text_answer": str}.
    Choice questions are graded locally and deterministically; open-ended ones and
    ALL explanations come from a single marking call so the learner always gets a
    full answer sheet, not just a score.
    """
    quiz = (await session.execute(select(Quiz).where(Quiz.id == quiz_id))).scalar_one_or_none()
    if quiz is None or quiz.user_id != user_id:
        raise ValueError("Quiz not found")
    questions = (
        (
            await session.execute(
                select(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id).order_by(QuizQuestion.ordinal)
            )
        )
        .scalars()
        .all()
    )
    if not questions:
        raise ValueError("Quiz has no questions")
    if question_ids:
        wanted = {qid for qid in question_ids}
        questions = [q for q in questions if q.id in wanted]
        if not questions:
            raise ValueError("No matching questions to grade")

    rows: list[dict] = []
    local: dict[int, tuple[bool, float]] = {}
    for q in questions:
        answer = answers.get(q.id) or {}
        selected = answer.get("selected_index")
        text_answer = str(answer.get("text_answer") or "")
        try:
            options = json.loads(q.options_json or "[]")
        except json.JSONDecodeError:
            options = []
        if q.question_type == "choice":
            is_correct = selected is not None and int(selected) == q.correct_index
            local[q.ordinal] = (is_correct, 1.0 if is_correct else 0.0)
            user_answer = options[selected] if isinstance(selected, int) and 0 <= selected < len(options) else ""
        else:
            local[q.ordinal] = (False, 0.0)  # decided by the marking pass
            user_answer = text_answer
        rows.append(
            {
                "ordinal": q.ordinal,
                "section_title": q.section_title,
                "question_type": q.question_type,
                "question": q.question,
                "options": options,
                "correct_index": q.correct_index,
                "reference_answer": q.reference_answer,
                "rubric": q.rubric,
                "user_answer": user_answer,
                "text_answer": text_answer,
                "selected_index": selected,
            }
        )

    # ---- marking pass: explanations for ALL questions, scores for open-ended ones
    explanations: dict[int, dict] = {}
    graded_count = 0
    try:
        explain_result = await router.complete(
            task="quiz_explain",
            messages=[
                ChatMessage(role="system", content=load_prompt("quiz_explain.v1.txt")),
                ChatMessage(role="user", content=_build_explain_prompt(rows)),
            ],
            user_id=user_id,
            source_id=quiz.source_id,
        )
        parsed = ExplainSchema.model_validate(parse_json_object(explain_result.content))
        for item in parsed.results:
            explanations[item.ordinal] = item.model_dump()
        graded_count = len(explanations)
    except Exception as exc:  # keep the record even if the marker is unreachable
        logger.warning("quiz_explain pass failed for quiz %s: %s", quiz_id, exc)

    details: list[dict] = []
    total = 0.0
    by_ordinal = {q.ordinal: q for q in questions}
    for row in rows:
        ordinal = row["ordinal"]
        question = by_ordinal[ordinal]
        explain = explanations.get(ordinal) or {}
        if row["question_type"] == "choice":
            correct, score = local[ordinal]
            verdict = "correct" if correct else "incorrect"
        else:
            score = _score_for(explain)
            verdict = str(explain.get("verdict") or "").strip() or (
                "correct" if score >= 0.999 else "partially_correct" if score > 0 else "incorrect"
            )
            correct = score >= 0.999
        total += score
        explanation = str(explain.get("explanation") or "").strip()
        if not explanation:
            explanation = _fallback_explanation(question, correct, row["text_answer"])
        details.append(
            {
                "question_id": str(question.id),
                "ordinal": ordinal,
                "section_title": row["section_title"],
                "question_type": row["question_type"],
                "question": row["question"],
                "selected_index": row["selected_index"],
                "text_answer": row["text_answer"],
                "user_answer": row["user_answer"],
                "correct_index": row["correct_index"] if row["question_type"] == "choice" else None,
                "reference_answer": row["reference_answer"],
                "correct": correct,
                "verdict": verdict,
                "score": round(score, 4),
                "ai_explanation": explanation,
            }
        )

    score_value = (total / len(rows)) if rows else 0.0
    attempt = QuizAttempt(
        quiz_id=quiz_id,
        user_id=user_id,
        answers_json=json.dumps(
            [
                {
                    "question_id": str(q.id),
                    "selected_index": (answers.get(q.id) or {}).get("selected_index"),
                    "text_answer": (answers.get(q.id) or {}).get("text_answer"),
                }
                for q in questions
            ],
            ensure_ascii=False,
        ),
        score=score_value,
        passed=score_value >= 0.6,
        details_json=json.dumps(details, ensure_ascii=False),
        graded_count=graded_count,
    )
    session.add(attempt)
    await session.commit()
    await session.refresh(attempt)
    return attempt


def load_details(attempt: QuizAttempt) -> list[dict]:
    try:
        return json.loads(attempt.details_json or "[]")
    except json.JSONDecodeError:
        return []


def submitted_at(attempt: QuizAttempt) -> datetime:
    return attempt.created_at
