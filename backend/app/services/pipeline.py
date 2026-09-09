from __future__ import annotations

import json
import shutil
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import DocumentChunk
from app.models.source import Source
from app.services.chunking import RawChunk, chunk_pages, chunk_segments
from app.services.knowledge import generate_summary_and_knowledge
from app.services.llm.base import ChatMessage
from app.services.llm.router import ModelRouter
from app.services.pdf_parser import parse_pdf
from app.services.progress import ProgressService
from app.services.storage import get_storage
from app.services.stt import extract_audio, get_stt
from app.utils.jsonutil import parse_json_object


class IngestPipeline:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.progress = ProgressService(session)
        self.router = ModelRouter(session)

    async def run(self, source_id: UUID, task_id: UUID) -> None:
        source = (await self.session.execute(select(Source).where(Source.id == source_id))).scalar_one()
        try:
            await self.progress.update(task_id, progress=5, step="download", status="running")
            data = await get_storage().get_bytes(source.storage_key)

            if source.kind == "video":
                chunks = await self._video_chunks(source, task_id, data)
            else:
                chunks = await self._pdf_chunks(task_id, data)

            await self.progress.update(task_id, progress=50, step="persist_chunks")
            await self._replace_chunks(source, chunks)

            await self.progress.update(task_id, progress=60, step="embed")
            await self._embed_chunks(source)

            await self.progress.update(task_id, progress=80, step="knowledge")
            summary, _ = await generate_summary_and_knowledge(
                self.session,
                source_id=source.id,
                user_id=source.user_id,
                router=self.router,
            )
            source.title = summary.title
            source.status = "ready"
            source.error_message = None
            await self.session.commit()
            await self.progress.update(task_id, progress=100, step="done", status="succeeded")
        except Exception as exc:
            source.status = "failed"
            source.error_message = str(exc)[:2000]
            await self.session.commit()
            await self.progress.update(
                task_id, progress=100, step="failed", status="failed", message=str(exc)[:2000]
            )
            raise

    async def _pdf_chunks(self, task_id: UUID, data: bytes) -> list[RawChunk]:
        await self.progress.update(task_id, progress=20, step="parse_pdf")
        pages = parse_pdf(data)
        await self.progress.update(task_id, progress=35, step="chunk")
        return chunk_pages([(p.page_number, p.text) for p in pages])

    async def _video_chunks(self, source: Source, task_id: UUID, data: bytes) -> list[RawChunk]:
        await self.progress.update(task_id, progress=15, step="ffmpeg")
        work, wav, _duration = await extract_audio(data)
        try:
            await self.progress.update(task_id, progress=25, step="stt")
            stt = get_stt()
            segments = await stt.transcribe(wav)
            await self.progress.update(task_id, progress=40, step="map_reduce")
            await self._map_reduce_segments(source, segments)
            return chunk_segments([(s.start, s.end, s.text) for s in segments])
        finally:
            shutil.rmtree(work, ignore_errors=True)

    async def _map_reduce_segments(self, source: Source, segments) -> None:
        """Summarize time windows independently (retry per window). Never dump the full transcript."""
        windows: list[list] = []
        current: list = []
        chars = 0
        for seg in segments:
            if chars + len(seg.text) > 800 and current:
                windows.append(current)
                current = []
                chars = 0
            current.append(seg)
            chars += len(seg.text)
        if current:
            windows.append(current)

        window_summaries: list[str] = []
        for i, window in enumerate(windows):
            body = "\n".join(f"[{s.start:.1f}-{s.end:.1f}] {s.text}" for s in window)
            last_exc: Exception | None = None
            for _attempt in range(3):
                try:
                    result = await self.router.complete(
                        task="segment_summarize",
                        messages=[
                            ChatMessage(
                                role="system",
                                content="Summarize this time window only. Return JSON.",
                            ),
                            ChatMessage(role="user", content=body),
                        ],
                        user_id=source.user_id,
                        source_id=source.id,
                    )
                    data = parse_json_object(result.content)
                    window_summaries.append(
                        json.dumps(
                            {
                                "window": i,
                                "start": window[0].start,
                                "end": window[-1].end,
                                "summary": data.get("summary") or result.content[:400],
                            },
                            ensure_ascii=False,
                        )
                    )
                    last_exc = None
                    break
                except Exception as exc:  # retry this window only
                    last_exc = exc
            if last_exc is not None:
                window_summaries.append(
                    json.dumps(
                        {
                            "window": i,
                            "start": window[0].start,
                            "end": window[-1].end,
                            "summary": " ".join(s.text for s in window)[:400],
                            "error": str(last_exc)[:200],
                        }
                    )
                )
        # Reduce: send window summaries, not the raw transcript.
        await self.router.complete(
            task="summarize",
            messages=[
                ChatMessage(role="system", content="Combine window summaries of a video lesson."),
                ChatMessage(role="user", content="\n".join(window_summaries)[:4000]),
            ],
            user_id=source.user_id,
            source_id=source.id,
        )

    async def _replace_chunks(self, source: Source, raw: list[RawChunk]) -> None:
        existing = (
            (await self.session.execute(select(DocumentChunk).where(DocumentChunk.source_id == source.id)))
            .scalars()
            .all()
        )
        for row in existing:
            await self.session.delete(row)
        await self.session.flush()
        for i, chunk in enumerate(raw):
            self.session.add(
                DocumentChunk(
                    source_id=source.id,
                    user_id=source.user_id,
                    ordinal=i,
                    content=chunk.content,
                    page_number=chunk.page_number,
                    start_time=chunk.start_time,
                    end_time=chunk.end_time,
                    locator=chunk.locator,
                )
            )
        await self.session.commit()

    async def _embed_chunks(self, source: Source) -> None:
        chunks = (
            (
                await self.session.execute(
                    select(DocumentChunk)
                    .where(DocumentChunk.source_id == source.id)
                    .order_by(DocumentChunk.ordinal)
                )
            )
            .scalars()
            .all()
        )
        batch_size = 16
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            result = await self.router.embed(
                task="embed",
                texts=[c.content for c in batch],
                user_id=source.user_id,
                source_id=source.id,
            )
            for chunk, vector in zip(batch, result.vectors, strict=False):
                chunk.embedding = vector
        await self.session.commit()
