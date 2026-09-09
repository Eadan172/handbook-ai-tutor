from __future__ import annotations

import math
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import DocumentChunk
from app.services.rag.base import RAGProvider, RetrievedChunk


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class PgVectorRAGProvider(RAGProvider):
    name = "pgvector"

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def retrieve(
        self,
        *,
        query: str,
        query_vector: list[float],
        source_id: UUID | None,
        user_id: UUID,
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        stmt = select(DocumentChunk).where(DocumentChunk.user_id == user_id)
        if source_id:
            stmt = stmt.where(DocumentChunk.source_id == source_id)
        chunks = (await self.session.execute(stmt)).scalars().all()
        scored: list[RetrievedChunk] = []
        for chunk in chunks:
            if not chunk.embedding:
                continue
            score = cosine(query_vector, list(chunk.embedding))
            scored.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    source_id=chunk.source_id,
                    content=chunk.content,
                    locator=chunk.locator,
                    page_number=chunk.page_number,
                    start_time=chunk.start_time,
                    end_time=chunk.end_time,
                    score=score,
                )
            )
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]
