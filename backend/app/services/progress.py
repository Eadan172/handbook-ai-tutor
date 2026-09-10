from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.task import Task


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProgressService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()

    async def update(
        self,
        task_id: UUID,
        *,
        progress: int,
        step: str,
        status: str | None = None,
        message: str | None = None,
    ) -> Task:
        task = (await self.session.execute(select(Task).where(Task.id == task_id))).scalar_one()
        task.progress = max(0, min(100, progress))
        task.step = step
        if status:
            task.status = status
        if message is not None:
            task.message = message
        task.updated_at = _utcnow()
        await self.session.commit()
        await self.session.refresh(task)
        await self._publish(task)
        return task

    async def _publish(self, task: Task) -> None:
        payload = json.dumps(
            {
                "id": str(task.id),
                "source_id": str(task.source_id),
                "status": task.status,
                "progress": task.progress,
                "step": task.step,
                "message": task.message,
            }
        )
        try:
            import redis.asyncio as redis

            client = redis.from_url(self.settings.redis_url)
            await client.set(f"task:{task.id}:progress", payload, ex=3600)
            await client.publish(f"task:{task.id}", payload)
            await client.aclose()
        except Exception:
            # SSE can still poll the database when Redis is down (inline/dev).
            return
