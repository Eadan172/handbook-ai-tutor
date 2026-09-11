from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.deps import get_current_user
from app.models.user import User
from app.services.llm.base import ChatMessage
from app.services.llm.router import LLMConfigError, ModelRouter, modality_for
from app.services.ocr import describe_ocr

router = APIRouter(prefix="/api/v1/llm", tags=["llm"])


class RouteRow(BaseModel):
    task: str
    modality: str
    provider: str
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    api_key_present: bool | None = None
    ready: bool
    error: str | None = None
    note: str | None = None


class RoutesOut(BaseModel):
    default_provider: str
    providers_config_path: str
    routes: list[RouteRow]
    ocr: dict | None = None


@router.get("/routes", response_model=RoutesOut)
async def get_routes(user: User = Depends(get_current_user)) -> RoutesOut:
    """Show which provider/model each task will actually call.

    Use this to confirm an API key in .env is really being picked up. The `ocr`
    block explains how image / scanned-PDF uploads are read, which is a separate
    decision from the LLM routes (`transcribe_image` is only the fallback).
    """
    r = ModelRouter()
    try:
        ocr = describe_ocr(r)
    except Exception as exc:  # diagnostics must never take the page down
        ocr = {"ready": False, "reason": f"{type(exc).__name__}: {exc}"}
    return RoutesOut(
        default_provider=r.default_name,
        providers_config_path=r.settings.providers_config_path,
        routes=[RouteRow(**row) for row in r.describe_routes()],
        ocr=ocr,
    )


class TestRequest(BaseModel):
    task: str = "summarize"
    prompt: str = "Reply with the single word: ok"


class TestOut(BaseModel):
    ok: bool
    task: str
    modality: str
    provider: str | None
    model: str | None
    reply: str | None = None
    error: str | None = None


@router.post("/test", response_model=TestOut)
async def test_route(body: TestRequest, user: User = Depends(get_current_user)) -> TestOut:
    """Round-trip a tiny prompt through the resolved provider for one task.

    Surfaces configuration and credential problems immediately instead of
    letting them hide behind MockLLM output.
    """
    r = ModelRouter()
    provider = None
    try:
        provider = r.provider_for(body.task)
        result = await r.complete(
            task=body.task,
            messages=[ChatMessage(role="user", content=body.prompt)],
            json_mode=False,
            source_id=None,
            user_id=user.id,
        )
    except LLMConfigError as exc:
        return TestOut(
            ok=False,
            task=body.task,
            modality=modality_for(body.task),
            provider=None,
            model=None,
            error=str(exc),
        )
    except Exception as exc:  # network / HTTP / auth errors from the vendor
        return TestOut(
            ok=False,
            task=body.task,
            modality=modality_for(body.task),
            provider=getattr(provider, "name", None),
            model=getattr(provider, "model_for", lambda _t: None)(body.task) if provider else None,
            error=f"{type(exc).__name__}: {exc}",
        )
    return TestOut(
        ok=True,
        task=body.task,
        modality=modality_for(body.task),
        provider=result.provider,
        model=result.model,
        reply=result.content[:500],
    )
