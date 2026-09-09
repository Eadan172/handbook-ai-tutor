from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AI Learning Tutor"
    secret_key: str = "change-me-in-production-use-a-long-random-string"
    debug: bool = False
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    database_url: str = "sqlite+aiosqlite:///./tutor.db"
    database_url_sync: str = "sqlite:///./tutor.db"

    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint: str = "http://localhost:9000"
    s3_public_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "sources"
    s3_region: str = "us-east-1"
    s3_secure: bool = False

    task_backend: str = "inline"  # arq | inline
    storage_backend: str = "local"  # minio | local
    local_storage_path: str = "./data/storage"

    rag_provider: str = "llamaindex"  # llamaindex | pgvector
    embedding_dim: int = 1536
    stt_provider: str = "mock"  # mock | faster_whisper

    llm_default_provider: str = "mock"
    providers_config_path: str = str(Path(__file__).resolve().parents[2] / "config" / "providers.yaml")

    jwt_expire_minutes: int = 60 * 24 * 7
    jwt_algorithm: str = "HS256"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
