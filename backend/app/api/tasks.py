from __future__ import annotations

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.core.db import SessionLocal, get_db
from app.core.deps import get_current_user
from app.domain.schemas import TaskOut
from app.models.task import Task
from app.models.user import User
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Task:
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{task_id}/events")
async def task_events(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found")

    async def gen():
        last = None
        while True:
            async with SessionLocal() as session:
                row = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one()
                payload = json.dumps(
                    {
                        "id": str(row.id),
                        "source_id": str(row.source_id),
                        "status": row.status,
                        "progress": row.progress,
                        "step": row.step,
                        "message": row.message,
                    }
                )
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            data = json.loads(payload)
            if data.get("status") in {"succeeded", "failed"}:
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream")
