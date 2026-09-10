from __future__ import annotations

import json
import urllib.parse
from io import BytesIO
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user, get_current_user_allow_query_token
from app.domain.schemas import (
    OutlineEntry,
    SourceDeleteOut,
    SourceOut,
    SourceStructureOut,
    StructureChunkOut,
    TaskOut,
)
from app.models.chunk import DocumentChunk
from app.models.source import Source
from app.models.task import Task
from app.models.user import User
from app.services.library import delete_source_cascade
from app.services.queue import get_queue
from app.services.storage import get_storage

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])

# Scope A originally accepted PDF + MP4 only, which rejected photos and scans of
# textbook pages outright. Images now go through the OCR stage like a scanned PDF.
ALLOWED: dict[str, str] = {
    "application/pdf": "pdf",
    "video/mp4": "video",
    "image/png": "image",
    "image/jpeg": "image",
    "image/webp": "image",
    "image/gif": "image",
    "image/bmp": "image",
    "image/tiff": "image",
}

EXTENSION_KINDS: dict[str, str] = {
    ".pdf": "pdf",
    ".mp4": "video",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".gif": "image",
    ".bmp": "image",
    ".tif": "image",
    ".tiff": "image",
}

SUPPORTED_HINT = "PDF, MP4, PNG, JPG, JPEG, WEBP, GIF, BMP or TIFF"


def _kind_for(file: UploadFile) -> str:
    name = (file.filename or "").lower()
    # Browsers sometimes append parameters, e.g. "text/plain; charset=utf-8".
    ctype = (file.content_type or "").lower().split(";")[0].strip()
    if ctype in ALLOWED:
        return ALLOWED[ctype]
    for extension, kind in EXTENSION_KINDS.items():
        if name.endswith(extension):
            return kind
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported file type. Supported: {SUPPORTED_HINT}.",
    )


@router.post("/upload", response_model=SourceOut)
async def upload_source(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SourceOut:
    kind = _kind_for(file)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if kind == "image":
        # Fail fast on a corrupt image instead of surfacing it minutes later from
        # deep inside the OCR stage. Image.open is lazy and only reads the header.
        try:
            with Image.open(BytesIO(data)) as probe:
                probe.verify()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not read this image ({type(exc).__name__}). "
                "Re-export it as PNG or JPG and try again.",
            ) from None
    source_id = uuid4()
    key = f"{user.id}/{source_id}/{file.filename or 'upload'}"
    storage = get_storage()
    await storage.ensure_ready()
    await storage.put_bytes(key, data, file.content_type or "application/octet-stream")

    source = Source(
        id=source_id,
        user_id=user.id,
        filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        kind=kind,
        storage_key=key,
        byte_size=len(data),
        status="queued",
        title=file.filename,
    )
    task = Task(user_id=user.id, source_id=source.id, kind="ingest", status="queued", progress=0, step="queued")
    db.add_all([source, task])
    await db.commit()
    await db.refresh(source)
    await db.refresh(task)

    job_id = await get_queue().enqueue_ingest(source.id, task.id)
    task.arq_job_id = job_id
    await db.commit()

    out = SourceOut.model_validate(source)
    out.task_id = task.id
    return out


@router.get("", response_model=list[SourceOut])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[SourceOut]:
    rows = (
        (await db.execute(select(Source).where(Source.user_id == user.id).order_by(Source.created_at.desc())))
        .scalars()
        .all()
    )
    return [SourceOut.model_validate(r) for r in rows]


@router.get("/{source_id}", response_model=SourceOut)
async def get_source(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SourceOut:
    source = await _owned_source(db, source_id, user.id)
    task = (
        await db.execute(
            select(Task).where(Task.source_id == source.id).order_by(Task.created_at.desc())
        )
    ).scalars().first()
    out = SourceOut.model_validate(source)
    out.task_id = task.id if task else None
    return out


async def _owned_source(db: AsyncSession, source_id: UUID, user_id: UUID) -> Source:
    source = (await db.execute(select(Source).where(Source.id == source_id))).scalar_one_or_none()
    if source is None or source.user_id != user_id:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.get("/{source_id}/structure", response_model=SourceStructureOut)
async def get_structure(
    source_id: UUID,
    limit: int = Query(default=300, ge=1, le=3000),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SourceStructureOut:
    """What the parser understood: page map, section tree, and typed chunks.

    Exposed so the reading can be inspected rather than trusted. If a section is
    missing or the page offset is wrong, it is visible here immediately instead
    of surfacing as a puzzling answer three questions later.
    """
    source = await _owned_source(db, source_id, user.id)

    outline: list[OutlineEntry] = []
    try:
        for raw in json.loads(source.section_outline_json or "[]"):
            outline.append(OutlineEntry.model_validate(raw))
    except Exception:
        outline = []

    chunks = (
        (
            await db.execute(
                select(DocumentChunk)
                .where(DocumentChunk.source_id == source.id)
                .order_by(DocumentChunk.ordinal)
            )
        )
        .scalars()
        .all()
    )

    counts: dict[str, int] = {}
    for chunk in chunks:
        key = chunk.content_type or "body"
        counts[key] = counts.get(key, 0) + 1

    section_index: dict[str, list[int]] = {}
    for chunk in chunks:
        if chunk.content_type != "heading" or not chunk.section_title:
            continue
        pages = section_index.setdefault(chunk.section_title, [])
        page = chunk.printed_page if chunk.printed_page is not None else chunk.page_number
        if page is not None and page not in pages:
            pages.append(page)

    return SourceStructureOut(
        source_id=source.id,
        page_offset=source.page_offset,
        page_count=source.page_count,
        outline=outline,
        content_types=counts,
        chunk_total=len(chunks),
        chunks=[
            StructureChunkOut(
                id=chunk.id,
                ordinal=chunk.ordinal,
                content_type=chunk.content_type or "body",
                section_title=chunk.section_title,
                page_number=chunk.page_number,
                printed_page=chunk.printed_page,
                locator=chunk.locator,
                heading_level=chunk.heading_level,
                preview=(chunk.content or "")[:160],
            )
            for chunk in chunks[:limit]
        ],
        section_index=section_index,
    )


@router.get("/{source_id}/file")
async def download_source_file(
    source_id: UUID,
    token: str | None = Query(default=None, description="JWT, for iframe/embed viewers"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user_allow_query_token),
) -> Response:
    """Stream the original upload back to the browser.

    Used by the left-hand PDF pane. `Content-Disposition: inline` lets the
    browser's built-in viewer render it in place; `?download=1` is handled by
    the frontend as a plain link.
    """
    source = await _owned_source(db, source_id, user.id)
    try:
        data = await get_storage().get_bytes(source.storage_key)
    except FileNotFoundError:
        raise HTTPException(status_code=410, detail="File is no longer in storage") from None
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Storage read failed: {exc}") from exc

    quoted = urllib.parse.quote(source.filename)
    return Response(
        content=data,
        media_type=source.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quoted}",
            "Cache-Control": "private, max-age=0, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{source_id}", response_model=SourceDeleteOut)
async def delete_source(
    source_id: UUID,
    delete_files: bool = Query(
        default=True,
        description="Also remove the stored file from local disk / MinIO. "
        "Set false to keep the blob and only drop database rows.",
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SourceDeleteOut:
    """Delete a source together with everything derived from it."""
    source = await _owned_source(db, source_id, user.id)
    report = await delete_source_cascade(
        db, source=source, storage=get_storage(), delete_files=delete_files
    )
    return SourceDeleteOut(
        source_id=report.source_id,
        filename=report.filename,
        storage_key=report.storage_key,
        storage_deleted=report.storage_deleted,
        storage_error=report.storage_error,
        rows_deleted=report.rows_deleted,
        total_rows_deleted=report.total_rows,
    )
