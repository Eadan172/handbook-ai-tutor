from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


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
    ) -> list[RetrievedChunk]:
        raise NotImplementedError
