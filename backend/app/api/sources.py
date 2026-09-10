from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.domain.schemas import SourceOut, TaskOut
from app.models.source import Source
from app.models.task import Task
from app.models.user import User
from app.services.queue import get_queue
from app.services.storage import get_storage

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])

ALLOWED = {
    "application/pdf": "pdf",
    "video/mp4": "video",
}


def _kind_for(file: UploadFile) -> str:
    name = (file.filename or "").lower()
    ctype = (file.content_type or "").lower()
    if ctype in ALLOWED:
        return ALLOWED[ctype]
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith(".mp4"):
        return "video"
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Only PDF and MP4 uploads are supported in Scope A",
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
