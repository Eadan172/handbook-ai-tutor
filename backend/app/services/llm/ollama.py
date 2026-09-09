from __future__ import annotations

import httpx

from app.core.config import get_settings
from app.services.llm.base import ChatMessage, EmbedResult, LLMProvider, LLMResult


class OllamaProvider(LLMProvider):
    """Optional local Ollama HTTP API. Disabled unless selected in providers.yaml."""

    def __init__(self, *, base_url: str, models: dict[str, str]) -> None:
        self.name = "ollama"
        self.base_url = base_url.rstrip("/")
        self.models = models
        self.dim = get_settings().embedding_dim

    def _model_for(self, task: str) -> str:
        return self.models.get(task) or self.models.get("default") or "llama3.2"

    async def complete(
        self,
        *,
        task: str,
        messages: list[ChatMessage],
        json_mode: bool = False,
    ) -> LLMResult:
        model = self._model_for(task)
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "format": "json" if json_mode else None,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        async with httpx.AsyncClient(timeout=180.0, trust_env=True) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        content = (data.get("message") or {}).get("content") or ""
        return LLMResult(
            content=content,
            prompt_tokens=int(data.get("prompt_eval_count") or 0),
            completion_tokens=int(data.get("eval_count") or 0),
            provider=self.name,
            model=model,
        )

    async def embed(self, *, task: str, texts: list[str]) -> EmbedResult:
        model = self.models.get("embed") or self._model_for("embed")
        vectors: list[list[float]] = []
        tokens = 0
        async with httpx.AsyncClient(timeout=180.0, trust_env=True) as client:
            for text in texts:
                resp = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": model, "prompt": text},
                )
                resp.raise_for_status()
                data = resp.json()
                vectors.append(data["embedding"])
                tokens += max(1, len(text) // 4)
        return EmbedResult(
            vectors=vectors,
            prompt_tokens=tokens,
            provider=self.name,
            model=model,
            dim=len(vectors[0]) if vectors else self.dim,
        )
