from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "llm_default_provider": settings.llm_default_provider,
        "task_backend": settings.task_backend,
        "storage_backend": settings.storage_backend,
        "stt_provider": settings.stt_provider,
        "rag_provider": settings.rag_provider,
    }
