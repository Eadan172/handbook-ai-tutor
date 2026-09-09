from __future__ import annotations

import os

import httpx

from app.core.config import get_settings
from app.services.llm.base import ChatMessage, EmbedResult, LLMProvider, LLMResult


class OpenAICompatibleProvider(LLMProvider):
    """Config-driven OpenAI-compatible HTTP API (DashScope, DeepSeek, SiliconFlow, OpenAI, …)."""

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        models: dict[str, str],
        timeout: float = 120.0,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.models = models
        self.timeout = timeout
        self.dim = get_settings().embedding_dim

    def _model_for(self, task: str) -> str:
        return self.models.get(task) or self.models.get("default") or "unknown"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def complete(
        self,
        *,
        task: str,
        messages: list[ChatMessage],
        json_mode: bool = False,
    ) -> LLMResult:
        model = self._model_for(task)
        payload: dict = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        # trust_env=True (default) honors HTTP(S)_PROXY — never hardcode a proxy
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=True) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        choice = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage") or {}
        return LLMResult(
            content=choice,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            provider=self.name,
            model=model,
        )

    async def embed(self, *, task: str, texts: list[str]) -> EmbedResult:
        model = self.models.get("embed") or self._model_for(task)
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=True) as client:
            resp = await client.post(
                f"{self.base_url}/embeddings",
                headers=self._headers(),
                json={"model": model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()
        items = sorted(data.get("data") or [], key=lambda x: x.get("index", 0))
        vectors = [item["embedding"] for item in items]
        usage = data.get("usage") or {}
        return EmbedResult(
            vectors=vectors,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            provider=self.name,
            model=model,
            dim=len(vectors[0]) if vectors else self.dim,
        )


def env_or_override(name: str, fallback: str = "") -> str:
    override = os.environ.get("OPENAI_COMPAT_API_KEY")
    if name == "OPENAI_COMPAT_API_KEY" or not os.environ.get(name):
        if os.environ.get("OPENAI_COMPAT_BASE_URL") and override:
            return override
    return os.environ.get(name, fallback)
