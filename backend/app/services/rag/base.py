from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass
class RetrievalFilter:
    """Structural constraints extracted from the learner's question.

    The learner names a page, a chapter, or asks for the book's shape. Those are
    exact, cheap constraints -- a page number is not a fuzzy semantic hint -- so
    they are applied as scoring terms rather than hoped for from cosine
    similarity. Nothing here is a hard cut: a page filter that matches nothing
    falls back to similarity, because refusing to answer is worse than answering
    from a neighbouring page.
    """

    #: Page numbers as guessed by the learner; matched against both the printed
    #: folio and the physical PDF index.
    pages: tuple[int, ...] = ()
    #: Chapter / section tokens, e.g. ("第3章", "3.2").
    section_terms: tuple[str, ...] = ()
    #: Content types to nudge up, e.g. ("formula",) for "这页的公式".
    prefer_types: tuple[str, ...] = ()
    #: Content types to nudge down: figure labels are noise for a prose question.
    avoid_types: tuple[str, ...] = ()
    #: Types removed outright. Page furniture is never an answer.
    exclude_types: tuple[str, ...] = ("header", "footer")

    def is_empty(self) -> bool:
        return not (self.pages or self.section_terms or self.prefer_types)


@dataclass
class RetrievedChunk:
    chunk_id: UUID
    source_id: UUID
    content: str
    locator: str | None
    page_number: int | None
    start_time: float | None
    end_time: float | None
    score: float
    printed_page: int | None = None
    section_title: str | None = None
    content_type: str = "body"
    heading_level: int | None = None


class RAGProvider(ABC):
    """Retrieval interface. LlamaIndex (or a stub) lives behind this."""

    name: str

    @abstractmethod
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
        raise NotImplementedError


def score_with_filters(chunk, base: float, filters: RetrievalFilter | None) -> float:
    """Re-rank a cosine score with the question's structural constraints.

    Weights are deliberately larger than the spread of a typical cosine
    neighbourhood: when a learner says "第569页", a chunk that *is* page 569 must
    beat a chunk that merely sounds like it, even if the wording is closer.
    """
    if filters is None:
        return base
    score = base

    if filters.pages:
        if chunk.printed_page in filters.pages or chunk.page_number in filters.pages:
            score += 0.55
        else:
            score -= 0.30

    if filters.section_terms:
        section = getattr(chunk, "section_title", "") or ""
        if any(term and term in section for term in filters.section_terms):
            score += 0.45
        else:
            score -= 0.20

    content_type = getattr(chunk, "content_type", "body") or "body"
    if content_type in filters.prefer_types:
        score += 0.25
    elif content_type in filters.avoid_types:
        score -= 0.25
    return score


__all__ = [
    "RAGProvider",
    "RetrievalFilter",
    "RetrievedChunk",
    "score_with_filters",
]
