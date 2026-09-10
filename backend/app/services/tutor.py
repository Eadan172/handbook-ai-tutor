from __future__ import annotations

import json
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.schemas import Citation
from app.models.tutor import TutorMessage
from app.prompts import load_prompt
from app.services.llm.base import ChatMessage
from app.services.llm.router import ModelRouter
from app.services.rag import get_rag
from app.utils.jsonutil import parse_model


class TutorReplySchema(BaseModel):
    reply: str
    citation_chunk_ids: list[str] = Field(default_factory=list)


async def retrieve_for_tutor(
    session: AsyncSession,
    *,
    query: str,
    source_id: UUID,
    user_id: UUID,
    router: ModelRouter,
    top_k: int = 5,
) -> list[Citation]:
    embed = await router.embed(task="embed", texts=[query], user_id=user_id, source_id=source_id)
    rag = get_rag(session)
    hits = await rag.retrieve(
        query=query,
        query_vector=embed.vectors[0],
        source_id=source_id,
        user_id=user_id,
        top_k=top_k,
    )
    return [
        Citation(
            chunk_id=h.chunk_id,
            source_id=h.source_id,
            locator=h.locator,
            page_number=h.page_number,
            start_time=h.start_time,
            end_time=h.end_time,
            quote=h.content[:400],
            score=h.score,
        )
        for h in hits
    ]


async def tutor_reply(
    session: AsyncSession,
    *,
    source_id: UUID,
    user_id: UUID,
    message: str,
    router: ModelRouter,
) -> TutorMessage:
    citations = await retrieve_for_tutor(
        session, query=message, source_id=source_id, user_id=user_id, router=router
    )
    excerpt_lines = []
    for c in citations:
        excerpt_lines.append(
            f"[chunk_id={c.chunk_id} locator={c.locator or ''}]\n{c.quote}"
        )
    user_prompt = (
        "Retrieved excerpts (cite only these):\n"
        + "\n\n".join(excerpt_lines)
        + f"\n\nLearner: {message}"
    )
    result = await router.complete(
        task="tutor",
        messages=[
            ChatMessage(role="system", content=load_prompt("tutor.v1.txt")),
            ChatMessage(role="user", content=user_prompt),
        ],
        user_id=user_id,
        source_id=source_id,
    )
    parsed = parse_model(result.content, TutorReplySchema)
    allowed = {str(c.chunk_id) for c in citations}
    used_ids = [cid for cid in parsed.citation_chunk_ids if cid in allowed]
    used = [c for c in citations if str(c.chunk_id) in used_ids] or citations[:2]
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
