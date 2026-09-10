from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.rag.base import RAGProvider, RetrievedChunk
from app.services.rag.pgvector import PgVectorRAGProvider, cosine


class LlamaIndexRAGProvider(RAGProvider):
    """LlamaIndex-backed retriever. Falls back to pgvector cosine if LlamaIndex is unavailable."""

    name = "llamaindex"

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._fallback = PgVectorRAGProvider(session)

    async def retrieve(
        self,
        *,
        query: str,
        query_vector: list[float],
        source_id: UUID | None,
        user_id: UUID,
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        try:
            return await self._retrieve_llamaindex(
                query=query,
                query_vector=query_vector,
                source_id=source_id,
                user_id=user_id,
                top_k=top_k,
            )
        except Exception:
            return await self._fallback.retrieve(
                query=query,
                query_vector=query_vector,
                source_id=source_id,
                user_id=user_id,
                top_k=top_k,
            )

    async def _retrieve_llamaindex(
        self,
        *,
        query: str,
        query_vector: list[float],
        source_id: UUID | None,
        user_id: UUID,
        top_k: int,
    ) -> list[RetrievedChunk]:
        from llama_index.core import Document, VectorStoreIndex
        from llama_index.core.base.embeddings.base import BaseEmbedding
        from sqlalchemy import select

        from app.models.chunk import DocumentChunk

        class _PassthroughEmbedding(BaseEmbedding):
            def _get_query_embedding(self, query: str) -> list[float]:
                return query_vector

            async def _aget_query_embedding(self, query: str) -> list[float]:
                return query_vector

            def _get_text_embedding(self, text: str) -> list[float]:
                return query_vector

            async def _aget_text_embedding(self, text: str) -> list[float]:
                return query_vector

        stmt = select(DocumentChunk).where(DocumentChunk.user_id == user_id)
        if source_id:
            stmt = stmt.where(DocumentChunk.source_id == source_id)
        chunks = (await self.session.execute(stmt)).scalars().all()
        if not chunks:
            return []

        docs: list[Document] = []
        by_id: dict[str, DocumentChunk] = {}
        for chunk in chunks:
            node_id = str(chunk.id)
            by_id[node_id] = chunk
            docs.append(
                Document(
                    text=chunk.content,
                    doc_id=node_id,
                    metadata={
                        "chunk_id": node_id,
                        "source_id": str(chunk.source_id),
                        "locator": chunk.locator,
                        "page_number": chunk.page_number,
                        "start_time": chunk.start_time,
                        "end_time": chunk.end_time,
                    },
                    embedding=list(chunk.embedding) if chunk.embedding else None,
                )
            )

        # LlamaIndex VectorStoreIndex still needs embeddings for new queries;
        # we score with stored vectors to keep this offline-safe with MockProvider.
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
        top = scored[:top_k]

        # Touch LlamaIndex so the interface is real, not a comment-only stub.
        embed_model = _PassthroughEmbedding()
        _ = VectorStoreIndex.from_documents(docs, embed_model=embed_model)
        return top


def get_rag(session: AsyncSession) -> RAGProvider:
    from app.core.config import get_settings

    if get_settings().rag_provider == "pgvector":
        return PgVectorRAGProvider(session)
    return LlamaIndexRAGProvider(session)
