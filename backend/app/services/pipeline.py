from __future__ import annotations

import json
import shutil
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.chunk import DocumentChunk
from app.models.source import Source
from app.services.chunking import (
    RawChunk,
    chunk_document,
    chunk_pages,
    chunk_segments,
)
from app.services.knowledge import generate_summary_and_knowledge
from app.services.layout import analyse_pdf, analyse_text_pages
from app.services.llm.base import ChatMessage
from app.services.llm.router import ModelRouter
from app.services.ocr import OcrUnavailable, get_ocr
from app.services.pdf_parser import (
    MIN_USABLE_CHARS,
    document_text_length,
    looks_textless,
    parse_pdf,
)
from app.services.progress import ProgressService
from app.services.storage import get_storage
from app.services.stt import extract_audio, get_stt
from app.utils.jsonutil import parse_json_object


class IngestError(RuntimeError):
    """Ingest failure with a message meant for the person who uploaded the file."""


#: Pages read by the layout probe that decides "text layer or scan". Kept small
#: because its only job is to answer that one question cheaply.
LAYOUT_PROBE_PAGES = 12


class IngestPipeline:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.progress = ProgressService(session)
        self.router = ModelRouter(session)
        # Provenance of the text extraction, surfaced in the task message so the
        # learner can tell real OCR from a mock transcription.
        self.extraction_note: str | None = None

    async def run(self, source_id: UUID, task_id: UUID) -> None:
        source = (await self.session.execute(select(Source).where(Source.id == source_id))).scalar_one()
        try:
            await self.progress.update(task_id, progress=5, step="download", status="running")
            data = await get_storage().get_bytes(source.storage_key)
            if not data:
                raise IngestError("The stored file is empty.")

            if source.kind == "video":
                chunks = await self._video_chunks(source, task_id, data)
            elif source.kind == "image":
                chunks = await self._image_chunks(source, task_id, data)
            else:
                chunks = await self._pdf_chunks(source, task_id, data)

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
            provider = self.router.provider_for("summarize")
            source.title = summary.title
            source.status = "ready"
            source.error_message = None
            await self.session.commit()
            note = getattr(self.router, "embed_note", None)
            detail = f"LLM: {provider.name} / {provider.model_for('summarize')}"
            if self.extraction_note:
                detail = f"{self.extraction_note} · {detail}"
            if note:
                detail += f" · {note}"
            await self.progress.update(
                task_id,
                progress=100,
                step="done",
                status="succeeded",
                message=detail,
            )
        except Exception as exc:
            detail = str(exc)[:2000]
            # Name the provider that failed so a bad key is obvious from the UI.
            try:
                provider = self.router.provider_for("summarize")
                detail = f"[{provider.name} / {provider.model_for('summarize')}] {detail}"
            except Exception:
                pass
            source.status = "failed"
            source.error_message = detail
            await self.session.commit()
            await self.progress.update(
                task_id, progress=100, step="failed", status="failed", message=detail
            )
            raise

    # ------------------------------------------------------------------ pdf

    async def _pdf_chunks(self, source: Source, task_id: UUID, data: bytes) -> list[RawChunk]:
        await self.progress.update(task_id, progress=15, step="parse_pdf")

        # Probe the first pages with the layout analyser before committing to a
        # full pass. On a scanned book the text runs are empty, which is a much
        # more reliable "needs OCR" signal than a character count, and it costs
        # a fraction of a full analysis.
        probe = analyse_pdf(data, max_pages=LAYOUT_PROBE_PAGES)
        if probe.has_text():
            doc = probe if not probe.truncated else analyse_pdf(data)
            await self.progress.update(task_id, progress=35, step="layout")
            self._record_structure(source, doc)
            counts = ", ".join(
                f"{kind}:{n}" for kind, n in sorted(doc.tallies.items()) if n
            )
            self.extraction_note = (
                f"text layer ({doc.char_count} chars, {len(doc.outline)} sections"
                + (f", 书内页码 {doc.page_offset:+d}" if doc.page_offset is not None else "")
                + f") · {counts}"
            )
            return chunk_document(doc)

        pages = parse_pdf(data)
        if not looks_textless(pages):
            # Layout extraction produced nothing but plain extraction has text
            # (an unusual content stream). Take the text, lose the structure.
            await self.progress.update(task_id, progress=35, step="chunk")
            self.extraction_note = f"text layer ({document_text_length(pages)} chars, no layout)"
            return chunk_pages([(p.page_number, p.text) for p in pages])

        # No usable text layer: this is a scan or a photo of a page. Re-read the
        # PDF pulling embedded images out, then OCR them.
        await self.progress.update(task_id, progress=20, step="ocr_prepare")
        pages = parse_pdf(data, extract_images=True)
        with_images = [p for p in pages if not p.has_text and p.image]
        if not with_images:
            raise IngestError(
                "This PDF has no text layer and no extractable page images, so there is "
                "nothing to read. Export the pages as PNG/JPG and upload those instead, "
                "or supply a PDF that contains a real text layer."
            )

        engine = get_ocr(self.router)
        settings = get_settings()
        cap = max(1, int(settings.ocr_max_pages or 40))
        selected = with_images[:cap]
        truncated = len(with_images) - len(selected)

        await self.progress.update(
            task_id,
            progress=30,
            step="ocr",
            message=f"OCR {len(selected)} page(s) via {engine.describe()}",
        )
        try:
            result = await engine.transcribe(
                [(p.page_number, p.image) for p in selected],
                user_id=source.user_id,
                source_id=source.id,
            )
        except OcrUnavailable as exc:
            raise IngestError(str(exc)) from exc

        self.extraction_note = f"OCR {result.provider}/{result.model} ({len(selected)} pages)"
        if result.note:
            self.extraction_note += f" · {result.note}"
        if truncated:
            self.extraction_note += f" · {truncated} page(s) beyond OCR_MAX_PAGES skipped"

        pages_out = [(p.page_number, p.text) for p in result.pages if p.text.strip()]
        if not pages_out:
            raise IngestError(
                f"OCR ran via {engine.describe()} but produced no text. "
                "The scan may be too low-resolution or rotated."
            )
        await self.progress.update(task_id, progress=40, step="chunk")
        return self._structure_ocr(source, pages_out)

    # ---------------------------------------------------------------- image

    async def _image_chunks(self, source: Source, task_id: UUID, data: bytes) -> list[RawChunk]:
        engine = get_ocr(self.router)
        await self.progress.update(
            task_id,
            progress=25,
            step="ocr",
            message=f"reading image via {engine.describe()}",
        )
        try:
            result = await engine.transcribe(
                [(1, data)],
                user_id=source.user_id,
                source_id=source.id,
            )
        except OcrUnavailable as exc:
            raise IngestError(str(exc)) from exc

        self.extraction_note = f"OCR {result.provider}/{result.model} ({source.filename})"
        if result.note:
            self.extraction_note += f" · {result.note}"

        pages_out = [(p.page_number, p.text) for p in result.pages if p.text.strip()]
        if not pages_out:
            raise IngestError(
                f"{engine.describe()} returned no text for this image. Try a sharper, "
                "straighter, higher-resolution photo."
            )
        await self.progress.update(task_id, progress=40, step="chunk")
        return self._structure_ocr(source, pages_out)

    def _structure_ocr(
        self, source: Source, pages_out: list[tuple[int, str]]
    ) -> list[RawChunk]:
        """Type and section-tag an OCR transcription.

        Coordinates are gone, so headings come from numbering and captions from
        their label. That is enough to stop figure text and captions from being
        embedded as prose, which is what made OCR'd books read as one long run-on
        paragraph.
        """
        doc = analyse_text_pages(pages_out)
        self._record_structure(source, doc)
        if doc.outline:
            self.extraction_note = (
                f"{self.extraction_note} · {len(doc.outline)} sections detected"
            )
        return chunk_document(doc)

    def _record_structure(self, source: Source, doc) -> None:
        """Persist the page map and section tree so retrieval can use them."""
        source.page_count = doc.total_pages or len(doc.pages)
        source.page_offset = doc.page_offset
        source.section_outline_json = json.dumps(
            [
                {
                    "level": node.level,
                    "number": node.number,
                    "title": node.title,
                    "page_number": node.page_number,
                    "printed_page": node.printed_page,
                    "page_end": node.page_end,
                }
                for node in doc.outline
            ],
            ensure_ascii=False,
        )

    # ---------------------------------------------------------------- video

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

    # -------------------------------------------------------------- shared

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
                    printed_page=chunk.printed_page,
                    start_time=chunk.start_time,
                    end_time=chunk.end_time,
                    locator=chunk.locator,
                    section_title=chunk.section_title or None,
                    content_type=chunk.content_type,
                    heading_level=chunk.heading_level,
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


__all__ = ["IngestError", "IngestPipeline", "MIN_USABLE_CHARS"]
