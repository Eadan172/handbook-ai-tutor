from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.domain.schemas import ImportRequest, ImportResult, TutorChatRequest, TutorMessageOut
from app.models.source import Source
from app.models.user import User
from app.services.exchange import apply_bundle, build_tutor_export
from app.services.llm.router import ModelRouter
from app.services.pipeline import source_readiness_error
from app.services.tutor import list_messages, message_to_out, tutor_reply

router = APIRouter(prefix="/api/v1/sources", tags=["tutor"])


@router.get("/{source_id}/tutor/messages", response_model=list[TutorMessageOut])
async def get_messages(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TutorMessageOut]:
    source = (await db.execute(select(Source).where(Source.id == source_id))).scalar_one_or_none()
    if source is None or source.user_id != user.id:
        raise HTTPException(status_code=404, detail="Source not found")
    rows = await list_messages(db, source_id, user.id)
    return [message_to_out(r) for r in rows]


@router.post("/{source_id}/tutor/chat", response_model=TutorMessageOut)
async def chat(
    source_id: UUID,
    body: TutorChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TutorMessageOut:
    source = (await db.execute(select(Source).where(Source.id == source_id))).scalar_one_or_none()
    if source is None or source.user_id != user.id:
        raise HTTPException(status_code=404, detail="Source not found")
    blocked = source_readiness_error(source)
    if blocked:
        raise HTTPException(status_code=409, detail=blocked)
    row = await tutor_reply(
        db,
        source_id=source_id,
        user_id=user.id,
        message=body.message,
        router=ModelRouter(db),
    )
    return message_to_out(row)


@router.get("/{source_id}/tutor/export")
async def export_tutor(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    source = (await db.execute(select(Source).where(Source.id == source_id))).scalar_one_or_none()
    if source is None or source.user_id != user.id:
        raise HTTPException(status_code=404, detail="Source not found")
    return await build_tutor_export(db, source=source, user_id=user.id)


@router.post("/{source_id}/tutor/import", response_model=ImportResult)
async def import_tutor(
    source_id: UUID,
    body: ImportRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ImportResult:
    source = (await db.execute(select(Source).where(Source.id == source_id))).scalar_one_or_none()
    if source is None or source.user_id != user.id:
        raise HTTPException(status_code=404, detail="Source not found")
    if body.mode not in {"merge", "replace"}:
        raise HTTPException(status_code=400, detail="mode must be 'merge' or 'replace'")
    counters = await apply_bundle(
        db, source=source, user_id=user.id, bundle=body.bundle.model_dump(), mode=body.mode
    )
    return ImportResult(mode=body.mode, **counters)
