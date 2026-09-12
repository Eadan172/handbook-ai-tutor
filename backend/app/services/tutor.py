from __future__ import annotations

import json
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.schemas import Citation
from app.models.source import Source
from app.models.tutor import TutorMessage
from app.prompts import load_prompt
from app.services.llm.base import ChatMessage
from app.services.llm.router import ModelRouter
from app.services.rag import get_rag
from app.services.rag.intent import QueryIntent, parse_intent
from app.utils.jsonutil import parse_model


class TutorReplySchema(BaseModel):
    reply: str
    citation_chunk_ids: list[str] = Field(default_factory=list)


def ground_citation_ids(claimed: list[str], allowed: set[str]) -> list[str]:
    """Keep only citation ids that were actually retrieved.

    A fabricated chunk id must not survive. Order follows the model so the
    learner sees the excerpts it said it used, not an arbitrary prefix.
    """
    seen: set[str] = set()
    grounded: list[str] = []
    for cid in claimed:
        key = str(cid)
        if key in allowed and key not in seen:
            grounded.append(key)
            seen.add(key)
    return grounded


_CITE_RETRY = (
    "上一轮 citation_chunk_ids 含有摘录里不存在的 id。只能引用上面出现的 "
    "chunk_id；若这段回答主要靠通用知识、没有用到摘录，请返回空数组。"
    "不要编造页码或 id。再次返回 JSON。"
)


def page_hint(source: Source | None) -> tuple[int, int] | None:
    """The document's printed page range, used to sanity-check page references."""
    if source is None or source.page_offset is None or not source.page_count:
        return None
    first = max(1, source.page_offset + 1)
    last = source.page_offset + source.page_count
    if last <= first:
        return None
    return first, last


async def _load_source(session: AsyncSession, source_id: UUID) -> Source | None:
    return (
        await session.execute(select(Source).where(Source.id == source_id))
    ).scalar_one_or_none()


async def plan_and_retrieve(
    session: AsyncSession,
    *,
    query: str,
    source_id: UUID,
    user_id: UUID,
    router: ModelRouter,
    top_k: int = 6,
) -> tuple[list[Citation], QueryIntent]:
    """Structure-aware retrieval.

    The question is parsed for a page, a chapter, or a request for the book's
    shape *before* embedding it, and those constraints are carried into the
    ranking. "第569页" therefore lands on the chunk that is page 569 rather than
    on whichever chunk happens to contain the words of the question.
    """
    source = await _load_source(session, source_id)
    intent = parse_intent(query, page_hint=page_hint(source))

    embed = await router.embed(task="embed", texts=[query], user_id=user_id, source_id=source_id)
    rag = get_rag(session)
    hits = await rag.retrieve(
        query=query,
        query_vector=embed.vectors[0],
        source_id=source_id,
        user_id=user_id,
        top_k=top_k,
        filters=intent.filter,
    )
    citations = [
        Citation(
            chunk_id=h.chunk_id,
            source_id=h.source_id,
            locator=h.locator,
            page_number=h.page_number,
            printed_page=h.printed_page,
            section_title=h.section_title,
            content_type=h.content_type,
            start_time=h.start_time,
            end_time=h.end_time,
            quote=h.content,
            score=h.score,
        )
        for h in hits
    ]
    return citations, intent


async def retrieve_for_tutor(
    session: AsyncSession,
    *,
    query: str,
    source_id: UUID,
    user_id: UUID,
    router: ModelRouter,
    top_k: int = 5,
) -> list[Citation]:
    citations, _intent = await plan_and_retrieve(
        session,
        query=query,
        source_id=source_id,
        user_id=user_id,
        router=router,
        top_k=top_k,
    )
    return citations


def format_excerpts(citations: list[Citation]) -> str:
    """One excerpt per citation, headed by everything that identifies it.

    Page (printed *and* physical), section path, and content type are all in the
    header so the model can answer structural questions from metadata instead of
    guessing from prose, and so it can label a formula as a formula.
    """
    lines: list[str] = []
    for c in citations:
        meta = [f"chunk_id={c.chunk_id}"]
        meta.append(f"type={c.content_type or 'body'}")
        if c.locator:
            meta.append(f"locator={c.locator}")
        else:
            if c.printed_page is not None:
                meta.append(f"printed_page={c.printed_page}")
            if c.page_number is not None:
                meta.append(f"pdf_page={c.page_number}")
        if c.section_title:
            meta.append(f"section={c.section_title}")
        header = " ".join(meta)
        lines.append(f"[{header}]\n{c.quote[:400]}")
    return "\n\n".join(lines)


async def tutor_reply(
    session: AsyncSession,
    *,
    source_id: UUID,
    user_id: UUID,
    message: str,
    router: ModelRouter,
) -> TutorMessage:
    citations, intent = await plan_and_retrieve(
        session,
        query=message,
        source_id=source_id,
        user_id=user_id,
        router=router,
    )

    scope_lines: list[str] = []
    if intent.filter.pages:
        scope_lines.append(
            "学习者问到页码："
            + ", ".join(str(p) for p in intent.filter.pages)
            + "（书内页码；与 PDF 页码可能不同）"
        )
    if intent.filter.section_terms:
        scope_lines.append("学习者问到章节：" + ", ".join(intent.filter.section_terms))
    if intent.wants_outline:
        scope_lines.append(
            "学习者在问全书结构。type=outline 的摘录是目录，请按它来答。"
        )

    parts: list[str] = []
    if scope_lines:
        parts.append("已理解的范围：\n" + "\n".join(f"- {line}" for line in scope_lines))
    parts.append(
        "检索到的原文摘录（引用时只能填这些 chunk_id；通用知识不要编造出处）：\n"
        + format_excerpts(citations)
    )
    parts.append(f"学习者：{message}")
    user_prompt = "\n\n".join(parts)

    result = await router.complete(
        task="tutor",
        messages=[
            ChatMessage(role="system", content=load_prompt("tutor.v3.txt")),
            ChatMessage(role="user", content=user_prompt),
        ],
        user_id=user_id,
        source_id=source_id,
    )
    parsed = parse_model(result.content, TutorReplySchema)
    allowed = {str(c.chunk_id) for c in citations}
    used_ids = ground_citation_ids(parsed.citation_chunk_ids, allowed)
    claimed = [str(cid) for cid in parsed.citation_chunk_ids]
    # Empty citations are allowed: the model may add its own knowledge.
    # Only retry when it invented an id that was never retrieved.
    needs_retry = any(cid not in allowed for cid in claimed)
    if needs_retry:
        retry = await router.complete(
            task="tutor",
            messages=[
                ChatMessage(role="system", content=load_prompt("tutor.v3.txt")),
                ChatMessage(role="user", content=user_prompt),
                ChatMessage(role="assistant", content=result.content),
                ChatMessage(role="user", content=_CITE_RETRY),
            ],
            user_id=user_id,
            source_id=source_id,
        )
        parsed = parse_model(retry.content, TutorReplySchema)
        used_ids = ground_citation_ids(parsed.citation_chunk_ids, allowed)
    used = [c for c in citations if str(c.chunk_id) in set(used_ids)]
    user_row = TutorMessage(
        source_id=source_id,
        user_id=user_id,
        role="user",
        content=message,
        citations_json="[]",
    )
    assistant_row = TutorMessage(
        source_id=source_id,
        user_id=user_id,
        role="assistant",
        content=parsed.reply,
        citations_json=json.dumps([c.model_dump(mode="json") for c in used], default=str),
    )
    session.add_all([user_row, assistant_row])
    await session.commit()
    await session.refresh(assistant_row)
    return assistant_row


async def list_messages(session: AsyncSession, source_id: UUID, user_id: UUID) -> list[TutorMessage]:
    return (
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


def message_to_out(row: TutorMessage):
    from app.domain.schemas import TutorMessageOut

    try:
        citations = [Citation.model_validate(c) for c in json.loads(row.citations_json or "[]")]
    except Exception:
        citations = []
    return TutorMessageOut(
        id=row.id,
        role=row.role,
        content=row.content,
        citations=citations,
        created_at=row.created_at,
    )
