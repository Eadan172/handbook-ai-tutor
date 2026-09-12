from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import DocumentChunk
from app.models.quiz import QUESTION_TYPES, Quiz, QuizAttempt, QuizQuestion
from app.models.source import Source
from app.prompts import load_prompt
from app.services.chunking import format_document_excerpts
from app.services.front_matter import exclude_front_matter, major_study_sections
from app.services.llm.base import ChatMessage
from app.services.llm.router import ModelRouter
from app.services.pipeline import source_readiness_error
from app.utils.jsonutil import parse_json_object

logger = logging.getLogger("app.quiz")

QUIZ_PROMPT_VERSION = "quiz_generate.v2"
EXPLAIN_PROMPT_VERSION = "quiz_explain.v2"

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
    """Document section titles in reading order, skipping outline and front matter."""
    return major_study_sections(chunks)


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
    source = (await session.execute(select(Source).where(Source.id == source_id))).scalar_one_or_none()
    if source is None:
        raise ValueError("资料不存在")
    blocked = source_readiness_error(source)
    if blocked:
        raise ValueError(blocked)
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
        raise ValueError("资料还没有可检索的原文切片。若解析已失败，请回到原文页查看原因后重新导入。")
    known = {str(c.id) for c in chunks}
    # Skip 前言 / 致谢 / preface so questions start at chapter 1.
    study_chunks = exclude_front_matter(chunks) or chunks
    sections = major_sections(study_chunks)
    if len(sections) >= _SECTION_GENERATE_MIN and len(study_chunks) >= _SECTION_GENERATE_CHUNK_MIN:
        title, questions = await _generate_per_section(
            study_chunks, router=router, user_id=user_id, source_id=source_id, sections=sections
        )
    else:
        excerpts = format_document_excerpts(study_chunks, max_chars=11000)
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


def _fmt_locator(chunk: DocumentChunk | None) -> str:
    if chunk is None:
        return ""
    if chunk.start_time is not None:
        s = max(0, int(chunk.start_time))
        stamp = f"{s // 60}:{s % 60:02d}"
        if chunk.end_time is not None:
            e = max(0, int(chunk.end_time))
            stamp += f"-{e // 60}:{e % 60:02d}"
        return f"视频 {stamp}"
    if chunk.printed_page is not None:
        extra = (
            f"（PDF 第 {chunk.page_number} 页）"
            if chunk.page_number and chunk.page_number != chunk.printed_page
            else ""
        )
        return f"书内第 {chunk.printed_page} 页{extra}"
    if chunk.page_number is not None:
        return f"第 {chunk.page_number} 页"
    return (chunk.locator or "").strip()


def _fallback_explanation(
    q: QuizQuestion,
    correct: bool,
    user_answer: str,
    *,
    locator: str = "",
) -> str:
    """Deterministic Chinese explanation used when the explain pass cannot run."""
    where = f"依据{locator}。" if locator else "依据原文。"
    if q.question_type == "choice":
        try:
            options = json.loads(q.options_json or "[]")
        except json.JSONDecodeError:
            options = []
        letter = (
            chr(65 + q.correct_index) if 0 <= q.correct_index < max(1, len(options)) else "?"
        )
        right = options[q.correct_index] if 0 <= q.correct_index < len(options) else "-"
        if not (user_answer or "").strip():
            return f"未作答。正确答案是 {letter}. {right}。{where}该选项符合原文表述。"
        if correct:
            return f"回答正确。{letter}. {right} 是对的，{where}"
        return f"回答不正确。正确答案是 {letter}. {right}。{where}"
    if not user_answer.strip():
        ref = (q.reference_answer or "").strip()
        hint = f"参考答案：{ref}" if ref else "请对照参考答案再答一次。"
        return f"未作答。{where}{hint}"
    return f"自动解析暂不可用。{where}请对照上面的参考答案。"


def _build_explain_prompt(rows: list[dict]) -> str:
    parts: list[str] = []
    for row in rows:
        lines = [
            f"ordinal={row['ordinal']}",
            f"section: {row['section_title'] or '-'}",
            f"type: {row['question_type']}",
            f"question: {row['question']}",
        ]
        if row.get("locator"):
            lines.append(f"locator: {row['locator']}")
        if row["question_type"] == "choice":
            options = row["options"]
            letter = (
                chr(65 + row["correct_index"])
                if isinstance(row["correct_index"], int) and row["correct_index"] >= 0
                else "?"
            )
            lines.append("options: " + " | ".join(f"{chr(65 + i)}. {o}" for i, o in enumerate(options)))
            lines.append(f"correct_index: {row['correct_index']} (选项 {letter})")
            if 0 <= int(row["correct_index"] or 0) < len(options):
                lines.append(f"correct_option: {letter}. {options[row['correct_index']]}")
        if row["reference_answer"]:
            lines.append(f"reference_answer: {row['reference_answer']}")
        if row["rubric"]:
            lines.append(f"rubric: {row['rubric']}")
        lines.append(f"learner_answer: {row['user_answer'] or '（未作答）'}")
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

    cited_ids: list[UUID] = []
    for q in questions:
        try:
            for raw_id in json.loads(q.chunk_ids_json or "[]"):
                cited_ids.append(UUID(str(raw_id)))
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
    chunks_by_id: dict[str, DocumentChunk] = {}
    if cited_ids:
        found = (
            (
                await session.execute(
                    select(DocumentChunk).where(DocumentChunk.id.in_(cited_ids))
                )
            )
            .scalars()
            .all()
        )
        chunks_by_id = {str(c.id): c for c in found}

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
        locator = ""
        try:
            for raw_id in json.loads(q.chunk_ids_json or "[]"):
                locator = _fmt_locator(chunks_by_id.get(str(raw_id)))
                if locator:
                    break
        except json.JSONDecodeError:
            locator = ""
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
                "locator": locator,
            }
        )

    # ---- marking pass: explanations for ALL questions, scores for open-ended ones
    explanations: dict[int, dict] = {}
    graded_count = 0
    try:
        explain_result = await router.complete(
            task="quiz_explain",
            messages=[
                ChatMessage(role="system", content=load_prompt("quiz_explain.v2.txt")),
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
            explanation = _fallback_explanation(
                question, correct, row["text_answer"], locator=row.get("locator") or ""
            )
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
