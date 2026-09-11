from __future__ import annotations

import json
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import DocumentChunk
from app.models.knowledge import KnowledgePoint, SourceSummary
from app.prompts import load_prompt
from app.services.chunking import format_document_excerpts
from app.services.llm.base import ChatMessage
from app.services.llm.router import ModelRouter
from app.utils.jsonutil import parse_model


class SummarySchema(BaseModel):
    title: str
    overview: str
    outline: list[str] = Field(default_factory=list)


class KnowledgePointSchema(BaseModel):
    title: str
    summary: str
    key_terms: list[str] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)


class KnowledgeExtractionSchema(BaseModel):
    points: list[KnowledgePointSchema]


def _valid_chunk_ids(raw: list[str], known: set[str]) -> list[str]:
    out: list[str] = []
    for item in raw:
        if item in known:
            out.append(item)
    return out


async def generate_summary_and_knowledge(
    session: AsyncSession,
    *,
    source_id: UUID,
    user_id: UUID,
    router: ModelRouter,
) -> tuple[SourceSummary, list[KnowledgePoint]]:
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
    known = {str(c.id) for c in chunks}
    # Structure-first sampling, so a 600-page book is summarised from its whole
    # shape instead of its cover page.
    excerpts = format_document_excerpts(chunks, max_chars=11000)

    summary_result = await router.complete(
        task="summarize",
        messages=[
            ChatMessage(role="system", content=load_prompt("summarize.v2.txt")),
            ChatMessage(role="user", content=excerpts),
        ],
        user_id=user_id,
        source_id=source_id,
    )
    parsed_summary = parse_model(summary_result.content, SummarySchema)

    existing_summary = (
        await session.execute(select(SourceSummary).where(SourceSummary.source_id == source_id))
    ).scalar_one_or_none()
    if existing_summary:
        await session.delete(existing_summary)
        await session.flush()

    summary = SourceSummary(
        source_id=source_id,
        title=parsed_summary.title,
        overview=parsed_summary.overview,
        outline_json=json.dumps(parsed_summary.outline, ensure_ascii=False),
        prompt_version="summarize.v2",
    )
    session.add(summary)

    knowledge_result = await router.complete(
        task="extract_knowledge",
        messages=[
            ChatMessage(role="system", content=load_prompt("extract_knowledge.v2.txt")),
            ChatMessage(role="user", content=excerpts),
        ],
        user_id=user_id,
        source_id=source_id,
    )
    parsed_knowledge = parse_model(knowledge_result.content, KnowledgeExtractionSchema)

    old_points = (
        (await session.execute(select(KnowledgePoint).where(KnowledgePoint.source_id == source_id)))
        .scalars()
        .all()
    )
    for point in old_points:
        await session.delete(point)
    await session.flush()

    stored: list[KnowledgePoint] = []
    for point in parsed_knowledge.points:
        row = KnowledgePoint(
            source_id=source_id,
            title=point.title,
            summary=point.summary,
            key_terms_json=json.dumps(point.key_terms, ensure_ascii=False),
            chunk_ids_json=json.dumps(_valid_chunk_ids(point.chunk_ids, known)),
            prompt_version="extract_knowledge.v1",
        )
        session.add(row)
        stored.append(row)
    await session.flush()
    return summary, stored
