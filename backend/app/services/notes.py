from __future__ import annotations

import json
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import DocumentChunk
from app.models.knowledge import KnowledgePoint, SourceSummary
from app.models.note import SourceNote
from app.prompts import load_prompt
from app.services.chunking import format_excerpts
from app.services.llm.base import ChatMessage
from app.services.llm.router import ModelRouter
from app.utils.jsonutil import parse_json_object

logger = logging.getLogger("app.notes")


async def generate_notes(
    session: AsyncSession,
    *,
    source_id: UUID,
    user_id: UUID,
    router: ModelRouter,
) -> tuple[list[SourceNote], str, str]:
    """Ask the LLM for study-note drafts grounded in the source.

    Returns (notes, provider, model) so the UI can show what was used.
    """
    summary = (
        await session.execute(select(SourceSummary).where(SourceSummary.source_id == source_id))
    ).scalar_one_or_none()
    points = (
        (
            await session.execute(
                select(KnowledgePoint).where(KnowledgePoint.source_id == source_id)
            )
        )
        .scalars()
        .all()
    )
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
    if summary is None and not points:
        raise ValueError("Nothing to build notes from yet; wait for ingest to finish.")

    body_parts = []
    if summary:
        body_parts.append(f"TITLE: {summary.title}\nOVERVIEW: {summary.overview}")
        try:
            outline = json.loads(summary.outline_json or "[]")
            if outline:
                body_parts.append("OUTLINE:\n" + "\n".join(f"- {o}" for o in outline))
        except json.JSONDecodeError:
            pass
    if points:
        body_parts.append(
            "KNOWLEDGE POINTS:\n"
            + "\n".join(f"- {p.title}: {p.summary}" for p in points)
        )
    if chunks:
        body_parts.append("EXCERPTS:\n" + format_excerpts(chunks, max_chars=4000))

    result = await router.complete(
        task="notes_generate",
        messages=[
            ChatMessage(role="system", content=load_prompt("notes_generate.v1.txt")),
            ChatMessage(role="user", content="\n\n".join(body_parts)),
        ],
        user_id=user_id,
        source_id=source_id,
    )
    data = parse_json_object(result.content)
    raw_notes = data.get("notes") or []

    existing = (
        (await session.execute(select(SourceNote).where(SourceNote.source_id == source_id)))
        .scalars()
        .all()
    )
    ordinal = len(existing)
    created: list[SourceNote] = []
    for item in raw_notes:
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        note = SourceNote(
            source_id=source_id,
            user_id=user_id,
            title=str(item.get("title") or "AI draft")[:255],
            content=content,
            origin="llm",
            anchor=(str(item.get("anchor"))[:255] if item.get("anchor") else None),
            ordinal=ordinal,
        )
        ordinal += 1
        session.add(note)
        created.append(note)
    if not created:
        raise ValueError("The model returned no notes; try again or check your LLM provider.")
    await session.commit()
    for note in created:
        await session.refresh(note)
    return created, result.provider, result.model
