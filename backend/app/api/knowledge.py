from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.domain.schemas import KnowledgePointOut, RetrieveRequest, RetrieveResponse, SummaryOut
from app.models.knowledge import KnowledgePoint, SourceSummary
from app.models.source import Source
from app.models.user import User
from app.services.llm.router import ModelRouter
from app.services.tutor import retrieve_for_tutor

router = APIRouter(prefix="/api/v1/sources", tags=["knowledge"])


async def _owned(db: AsyncSession, source_id: UUID, user_id: UUID) -> Source:
    source = (await db.execute(select(Source).where(Source.id == source_id))).scalar_one_or_none()
    if source is None or source.user_id != user_id:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.get("/{source_id}/summary", response_model=SummaryOut)
async def get_summary(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SummaryOut:
    await _owned(db, source_id, user.id)
    row = (await db.execute(select(SourceSummary).where(SourceSummary.source_id == source_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Summary not ready")
    return SummaryOut(
        source_id=source_id,
        title=row.title,
        overview=row.overview,
        outline=json.loads(row.outline_json or "[]"),
        prompt_version=row.prompt_version,
    )


@router.get("/{source_id}/knowledge", response_model=list[KnowledgePointOut])
async def get_knowledge(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[KnowledgePointOut]:
    await _owned(db, source_id, user.id)
    rows = (
        (await db.execute(select(KnowledgePoint).where(KnowledgePoint.source_id == source_id)))
        .scalars()
        .all()
    )
    out: list[KnowledgePointOut] = []
    for row in rows:
        out.append(
            KnowledgePointOut(
                id=row.id,
                title=row.title,
                summary=row.summary,
                key_terms=json.loads(row.key_terms_json or "[]"),
                chunk_ids=json.loads(row.chunk_ids_json or "[]"),
            )
        )
    return out


@router.post("/{source_id}/retrieve", response_model=RetrieveResponse)
async def retrieve(
    source_id: UUID,
    body: RetrieveRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RetrieveResponse:
    await _owned(db, source_id, user.id)
    router_llm = ModelRouter(db)
    citations = await retrieve_for_tutor(
        db,
        query=body.query,
        source_id=source_id,
        user_id=user.id,
        router=router_llm,
        top_k=body.top_k,
    )
    return RetrieveResponse(citations=citations)
