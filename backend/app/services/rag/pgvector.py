from __future__ import annotations

import math
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import DocumentChunk
from app.services.rag.base import (
    RAGProvider,
    RetrievalFilter,
    RetrievedChunk,
    score_with_filters,
)


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def to_retrieved(chunk: DocumentChunk, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk.id,
        source_id=chunk.source_id,
        content=chunk.content,
        locator=chunk.locator,
        page_number=chunk.page_number,
        start_time=chunk.start_time,
        end_time=chunk.end_time,
        score=score,
        printed_page=chunk.printed_page,
        section_title=chunk.section_title,
        content_type=chunk.content_type or "body",
        heading_level=chunk.heading_level,
    )


def rank(
    chunks: list[DocumentChunk],
    query_vector: list[float],
    *,
    top_k: int,
    filters: RetrievalFilter | None,
) -> list[RetrievedChunk]:
    """Score, apply structural re-ranking, and take the head.

    Filtering happens here rather than in SQL because the working set is one
    source's chunks, and because a page filter must be a *preference*: if no
    chunk matches "第569页" the learner still deserves the closest prose rather
    than an empty answer.
    """
    # Page furniture is never content: a running head ("242 第4章 …") is the
    # same text on every page and would otherwise match almost any question.
    exclude = {"header", "footer"}
    if filters:
        exclude |= set(filters.exclude_types)
    scored: list[RetrievedChunk] = []
    for chunk in chunks:
        content_type = chunk.content_type or "body"
        if content_type in exclude:
            continue
        if not chunk.embedding:
            continue
        base = cosine(query_vector, list(chunk.embedding))
        scored.append(to_retrieved(chunk, score_with_filters(chunk, base, filters)))

    # Heading and outline chunks are short, so cosine under-rates them; but they
    # are exactly what a structural question needs, hence the explicit bonus.
    for item in scored:
        if item.content_type == "outline":
            item.score += 0.12
        elif item.content_type == "heading":
            item.score += 0.06

    scored.sort(key=lambda x: x.score, reverse=True)

    if filters is not None and filters.pages:
        # Guarantee first-class treatment for an exact page hit: a learner who
        # types "第569页" should see page 569 first even at low similarity.
        #
        # Three tiers, not two. A 649-page book with 27 pages of front matter
        # has *two* readings of "569": the folio printed on the paper (physical
        # 596) and the PDF's own counter (printed 542). Both are legitimate and
        # both are kept, but the printed folio wins, because the locator tells
        # the learner "书内 p.569 · PDF p.596" and the book's own numbering is
        # what a textbook question refers to.
        printed_hits: list[RetrievedChunk] = []
        physical_hits: list[RetrievedChunk] = []
        rest: list[RetrievedChunk] = []
        for item in scored:
            if item.printed_page in filters.pages:
                printed_hits.append(item)
            elif item.page_number in filters.pages:
                physical_hits.append(item)
            else:
                rest.append(item)
        return (printed_hits + physical_hits + rest)[:top_k]

    return scored[:top_k]


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
        filters: RetrievalFilter | None = None,
    ) -> list[RetrievedChunk]:
        stmt = select(DocumentChunk).where(DocumentChunk.user_id == user_id)
        if source_id:
            stmt = stmt.where(DocumentChunk.source_id == source_id)
        chunks = (await self.session.execute(stmt)).scalars().all()
        return rank(chunks, query_vector, top_k=top_k, filters=filters)
