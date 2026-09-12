from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.domain.schemas import UsageOut, UsageSourceRow, UsageTaskRow
from app.models.source import Source
from app.models.usage import TokenUsage
from app.models.user import User

router = APIRouter(prefix="/api/v1", tags=["usage"])


def _task_row(task: str, provider: str, model: str, calls: int, prompt: int, completion: int) -> UsageTaskRow:
    return UsageTaskRow(
        task=task,
        provider=provider,
        model=model,
        calls=calls,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
    )


def _rollup_tasks(rows: list[TokenUsage]) -> list[UsageTaskRow]:
    buckets: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    for row in rows:
        key = (row.task, row.provider, row.model)
        buckets[key][0] += 1
        buckets[key][1] += int(row.prompt_tokens or 0)
        buckets[key][2] += int(row.completion_tokens or 0)
    out = [
        _task_row(task, provider, model, calls, prompt, completion)
        for (task, provider, model), (calls, prompt, completion) in buckets.items()
    ]
    out.sort(key=lambda r: (-r.total_tokens, r.task, r.provider))
    return out


def _usage_out(rows: list[TokenUsage], sources: dict[UUID, Source]) -> UsageOut:
    prompt = sum(int(r.prompt_tokens or 0) for r in rows)
    completion = sum(int(r.completion_tokens or 0) for r in rows)
    by_source_rows: dict[UUID | None, list[TokenUsage]] = defaultdict(list)
    for row in rows:
        by_source_rows[row.source_id].append(row)
    source_out: list[UsageSourceRow] = []
    for source_id, group in by_source_rows.items():
        src = sources.get(source_id) if source_id else None
        p = sum(int(r.prompt_tokens or 0) for r in group)
        c = sum(int(r.completion_tokens or 0) for r in group)
        source_out.append(
            UsageSourceRow(
                source_id=source_id,
                source_title=(src.title if src else None),
                source_filename=(src.filename if src else None),
                prompt_tokens=p,
                completion_tokens=c,
                total_tokens=p + c,
                calls=len(group),
                by_task=_rollup_tasks(group),
            )
        )
    source_out.sort(key=lambda r: (-r.total_tokens, str(r.source_id or "")))
    return UsageOut(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        calls=len(rows),
        by_source=source_out,
        by_task=_rollup_tasks(rows),
    )


@router.get("/usage", response_model=UsageOut)
async def get_usage(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UsageOut:
    """Per-source and per-task token totals for the signed-in learner.

    Mock providers still write rows (often small non-zero counts from the
    character heuristic). No dollar prices are invented.
    """
    rows = list(
        (
            await db.execute(
                select(TokenUsage)
                .where(TokenUsage.user_id == user.id)
                .order_by(TokenUsage.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    source_ids = {r.source_id for r in rows if r.source_id}
    sources: dict[UUID, Source] = {}
    if source_ids:
        for src in (
            (await db.execute(select(Source).where(Source.id.in_(source_ids)))).scalars().all()
        ):
            sources[src.id] = src
    return _usage_out(rows, sources)


@router.get("/sources/{source_id}/usage", response_model=UsageOut)
async def get_source_usage(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UsageOut:
    source = (await db.execute(select(Source).where(Source.id == source_id))).scalar_one_or_none()
    if source is None or source.user_id != user.id:
        raise HTTPException(status_code=404, detail="Source not found")
    rows = list(
        (
            await db.execute(
                select(TokenUsage)
                .where(TokenUsage.user_id == user.id, TokenUsage.source_id == source_id)
                .order_by(TokenUsage.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return _usage_out(rows, {source.id: source})
