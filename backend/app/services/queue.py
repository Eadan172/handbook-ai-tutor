from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from uuid import UUID

from app.core.config import get_settings


class QueueProvider(ABC):
    @abstractmethod
    async def enqueue_ingest(self, source_id: UUID, task_id: UUID) -> str | None:
        raise NotImplementedError


class InlineQueue(QueueProvider):
    """Runs the ingest pipeline in-process. Used for tests and docker-less dev."""

    async def enqueue_ingest(self, source_id: UUID, task_id: UUID) -> str | None:
        from app.workers.jobs import ingest_source

        asyncio.create_task(ingest_source({}, str(source_id), str(task_id)))
        return f"inline:{task_id}"


class ArqQueue(QueueProvider):
    async def enqueue_ingest(self, source_id: UUID, task_id: UUID) -> str | None:
        from arq import create_pool
        from arq.connections import RedisSettings

        redis = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        try:
            job = await redis.enqueue_job("ingest_source", str(source_id), str(task_id))
            return job.job_id if job else None
        finally:
            await redis.aclose()


def get_queue() -> QueueProvider:
    if get_settings().task_backend == "arq":
        return ArqQueue()
    return InlineQueue()
