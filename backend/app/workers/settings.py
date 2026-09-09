from arq.connections import RedisSettings

from app.core.config import get_settings
from app.workers.jobs import ingest_source


class WorkerSettings:
    functions = [ingest_source]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 4
    job_timeout = 60 * 30
    keep_result = 3600
