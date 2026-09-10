from __future__ import annotations

from uuid import UUID

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.services.pipeline import IngestPipeline


async def ingest_source(ctx: dict, source_id: str, task_id: str) -> None:
    """ARQ job (and inline queue) entrypoint."""
    async with SessionLocal() as session:
        pipeline = IngestPipeline(session)
        await pipeline.run(UUID(source_id), UUID(task_id))


class WorkerSettings:
    functions = [ingest_source]
    redis_settings = None
    max_jobs = 4
    job_timeout = 60 * 30

    def __init__(self) -> None:
        from arq.connections import RedisSettings

        type(self).redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
