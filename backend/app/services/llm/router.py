from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.usage import TokenUsage
from app.services.llm.anthropic import AnthropicProvider
from app.services.llm.base import ChatMessage, EmbedResult, LLMProvider, LLMResult
from app.services.llm.mock import MockProvider
from app.services.llm.ollama import OllamaProvider
from app.services.llm.openai_compatible import OpenAICompatibleProvider


class ModelRouter:
    """Routes task="..." to a configured provider. Records TokenUsage on every call."""

    def __init__(self, session: AsyncSession | None = None) -> None:
        self.session = session
        self.settings = get_settings()
        self.config = self._load_config()
        self.providers = self._build_providers()
        self.task_routes: dict[str, str] = {
            str(k): str(v) for k, v in (self.config.get("task_routes") or {}).items()
        }
        self.default_name = (
            self.settings.llm_default_provider
            or self.config.get("default_provider")
            or "mock"
        )

    def _load_config(self) -> dict:
        path = Path(self.settings.providers_config_path)
        if not path.exists():
            return {"default_provider": "mock", "task_routes": {}, "providers": {"mock": {"type": "mock"}}}
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    def _build_providers(self) -> dict[str, LLMProvider]:
        built: dict[str, LLMProvider] = {"mock": MockProvider()}
        for name, spec in (self.config.get("providers") or {}).items():
            ptype = (spec or {}).get("type", "mock")
            models = (spec or {}).get("models") or {}
            if ptype == "mock":
                built[name] = MockProvider(
                    model=models.get("default", "mock-llm"),
                    embed_model=models.get("embed", "mock-embed"),
                )
            elif ptype == "openai_compatible":
                key_env = spec.get("api_key_env") or ""
                api_key = os.environ.get(key_env, "") if key_env else ""
                base_url = os.environ.get("OPENAI_COMPAT_BASE_URL") or spec.get("base_url") or ""
                if name == "openai_compat" and os.environ.get("OPENAI_COMPAT_MODEL"):
                    models = {**models, "default": os.environ["OPENAI_COMPAT_MODEL"]}
                built[name] = OpenAICompatibleProvider(
                    name=name,
                    base_url=base_url,
                    api_key=api_key,
                    models=models,
                )
            elif ptype == "ollama":
                base = os.environ.get("OLLAMA_BASE_URL") or spec.get("base_url") or "http://127.0.0.1:11434"
                built[name] = OllamaProvider(base_url=base, models=models)
            elif ptype == "anthropic":
                key_env = spec.get("api_key_env") or "ANTHROPIC_API_KEY"
                built[name] = AnthropicProvider(
                    name=name,
                    base_url=spec.get("base_url") or "https://api.anthropic.com",
                    api_key=os.environ.get(key_env, ""),
                    models=models,
                )
        return built

    def provider_for(self, task: str) -> LLMProvider:
        name = self.task_routes.get(task) or self.default_name
        provider = self.providers.get(name) or self.providers["mock"]
        return provider

    async def complete(
        self,
        *,
        task: str,
        messages: list[ChatMessage] | list[dict],
        json_mode: bool = True,
        user_id: UUID | None = None,
        source_id: UUID | None = None,
    ) -> LLMResult:
        normalized: list[ChatMessage] = [
            m if isinstance(m, ChatMessage) else ChatMessage.model_validate(m) for m in messages
        ]
        result = await self.provider_for(task).complete(task=task, messages=normalized, json_mode=json_mode)
        await self._record(task, result, user_id=user_id, source_id=source_id)
        return result

    async def embed(
        self,
        *,
        task: str = "embed",
        texts: list[str],
        user_id: UUID | None = None,
        source_id: UUID | None = None,
    ) -> EmbedResult:
        result = await self.provider_for(task).embed(task=task, texts=texts)
        await self._record(
            task,
            LLMResult(
                content="",
                prompt_tokens=result.prompt_tokens,
                completion_tokens=0,
                provider=result.provider,
                model=result.model,
            ),
            user_id=user_id,
            source_id=source_id,
        )
        return result

    async def _record(
        self,
        task: str,
        result: LLMResult,
        *,
        user_id: UUID | None,
        source_id: UUID | None,
    ) -> None:
        if self.session is None:
            return
        self.session.add(
            TokenUsage(
                user_id=user_id,
                source_id=source_id,
                task=task,
                provider=result.provider,
                model=result.model,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
            )
        )
        await self.session.flush()
