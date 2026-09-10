from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.domain.schemas import (
    ImportRequest,
    ImportResult,
    NoteCreate,
    NoteOut,
    NoteUpdate,
    RegenerateOut,
    SourceBundle,
)
from app.models.knowledge import KnowledgePoint
from app.models.note import SourceNote
from app.models.source import Source
from app.models.user import User
from app.services.exchange import apply_bundle, build_bundle
from app.services.knowledge import generate_summary_and_knowledge
from app.services.llm.router import LLMConfigError, ModelRouter
from app.services.notes import generate_notes

logger = logging.getLogger("app.notes.api")

router = APIRouter(prefix="/api/v1", tags=["notes"])


async def _owned_source(db: AsyncSession, source_id: UUID, user_id: UUID) -> Source:
    source = (await db.execute(select(Source).where(Source.id == source_id))).scalar_one_or_none()
    if source is None or source.user_id != user_id:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


def _note_out(note: SourceNote) -> NoteOut:
    return NoteOut(
        id=note.id,
        source_id=note.source_id,
        title=note.title,
        content=note.content,
        origin=note.origin,
        anchor=note.anchor,
        ordinal=note.ordinal,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


# --------------------------------------------------------------------- notes


@router.get("/sources/{source_id}/notes", response_model=list[NoteOut])
async def list_notes(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[NoteOut]:
    await _owned_source(db, source_id, user.id)
    rows = (
        (
            await db.execute(
                select(SourceNote)
                .where(SourceNote.source_id == source_id, SourceNote.user_id == user.id)
                .order_by(SourceNote.ordinal, SourceNote.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [_note_out(n) for n in rows]


@router.post("/sources/{source_id}/notes", response_model=NoteOut)
async def create_note(
    source_id: UUID,
    body: NoteCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NoteOut:
    await _owned_source(db, source_id, user.id)
    count = len(
        (
            await db.execute(select(SourceNote.id).where(SourceNote.source_id == source_id))
        )
        .scalars()
        .all()
    )
    note = SourceNote(
        source_id=source_id,
        user_id=user.id,
        title=body.title[:255],
        content=body.content,
        origin=body.origin or "manual",
        anchor=body.anchor,
        ordinal=count,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return _note_out(note)


@router.patch("/notes/{note_id}", response_model=NoteOut)
async def update_note(
    note_id: UUID,
    body: NoteUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NoteOut:
    note = (await db.execute(select(SourceNote).where(SourceNote.id == note_id))).scalar_one_or_none()
    if note is None or note.user_id != user.id:
        raise HTTPException(status_code=404, detail="Note not found")
    if body.title is not None:
        note.title = body.title[:255]
    if body.content is not None:
        note.content = body.content
    if body.anchor is not None:
        note.anchor = body.anchor
    await db.commit()
    await db.refresh(note)
    return _note_out(note)


@router.delete("/notes/{note_id}")
async def delete_note(
    note_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    note = (await db.execute(select(SourceNote).where(SourceNote.id == note_id))).scalar_one_or_none()
    if note is None or note.user_id != user.id:
        raise HTTPException(status_code=404, detail="Note not found")
    await db.delete(note)
    await db.commit()
    return {"deleted": True, "id": str(note_id)}


@router.post("/sources/{source_id}/notes/generate", response_model=list[NoteOut])
async def generate_notes_endpoint(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[NoteOut]:
    """Ask the LLM for extra note drafts based on the current summary + knowledge points."""
    await _owned_source(db, source_id, user.id)
    try:
        notes, _, _ = await generate_notes(
            db, source_id=source_id, user_id=user.id, router=ModelRouter(db)
        )
    except LLMConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return [_note_out(n) for n in notes]


# -------------------------------------------------------- export / import


@router.get("/sources/{source_id}/export", response_model=SourceBundle)
async def export_source(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SourceBundle:
    """Full snapshot of summary, knowledge, notes, quizzes and submission records."""
    source = await _owned_source(db, source_id, user.id)
    data = await build_bundle(db, source=source, user_id=user.id)
    return SourceBundle.model_validate(data)


@router.post("/sources/{source_id}/import", response_model=ImportResult)
async def import_source(
    source_id: UUID,
    body: ImportRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ImportResult:
    source = await _owned_source(db, source_id, user.id)
    if body.mode not in {"merge", "replace"}:
        raise HTTPException(status_code=400, detail="mode must be 'merge' or 'replace'")
    counters = await apply_bundle(
        db, source=source, user_id=user.id, bundle=body.bundle.model_dump(), mode=body.mode
    )
    return ImportResult(mode=body.mode, **counters)


@router.post("/sources/{source_id}/regenerate", response_model=RegenerateOut)
async def regenerate_knowledge(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RegenerateOut:
    """Re-run summary + knowledge extraction through the configured LLM."""
    source = await _owned_source(db, source_id, user.id)
    if source.status != "ready":
        raise HTTPException(status_code=409, detail="Source is not ready yet")
    router_llm = ModelRouter(db)
    try:
        summary, points = await generate_summary_and_knowledge(
            db, source_id=source.id, user_id=user.id, router=router_llm
        )
        await db.commit()
    except LLMConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc

    source.title = summary.title
    await db.commit()
    provider = router_llm.provider_for("summarize")
    return RegenerateOut(
        source_id=source.id,
        provider=provider.name,
        model=provider.model_for("summarize"),
        title=summary.title,
        knowledge_points=len(points),
    )


@router.get("/sources/{source_id}/knowledge/raw")
async def raw_knowledge(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Convenience JSON for copy-paste export from the browser."""
    await _owned_source(db, source_id, user.id)
    rows = (
        (await db.execute(select(KnowledgePoint).where(KnowledgePoint.source_id == source_id)))
        .scalars()
        .all()
    )
    return {
        "source_id": str(source_id),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "knowledge": [
            {
                "title": r.title,
                "summary": r.summary,
                "key_terms": json.loads(r.key_terms_json or "[]"),
            }
            for r in rows
        ],
    }
