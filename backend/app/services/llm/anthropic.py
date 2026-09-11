from __future__ import annotations

import httpx

from app.core.config import get_settings
from app.services.llm.base import (
    ChatMessage,
    EmbedResult,
    ImagePart,
    LLMProvider,
    LLMResult,
    TextPart,
)
from app.services.llm.mock import mock_embed_vectors


def _anthropic_content(content) -> str | list[dict]:
    """Anthropic Messages API content blocks."""
    if isinstance(content, str):
        return content
    blocks: list[dict] = []
    for part in content:
        if isinstance(part, TextPart):
            blocks.append({"type": "text", "text": part.text})
        elif isinstance(part, ImagePart):
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": part.mime,
                        "data": part.base64_payload,
                    },
                }
            )
    return blocks or ""


class AnthropicProvider(LLMProvider):
    """Optional Anthropic Messages HTTP API (no vendor SDK). Embeddings fall back to mock vectors."""

    def __init__(self, *, name: str, base_url: str, api_key: str, models: dict[str, str]) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.models = models
        self.dim = get_settings().embedding_dim

    def _model_for(self, task: str) -> str:
        return self.models.get(task) or self.models.get("default") or "claude-3-5-haiku-latest"

    async def complete(
        self,
        *,
        task: str,
        messages: list[ChatMessage],
        json_mode: bool = False,
    ) -> LLMResult:
        model = self._model_for(task)
        system = "\n".join(m.text() for m in messages if m.role == "system")
        body_messages = [
            {"role": m.role, "content": _anthropic_content(m.content)}
            for m in messages
            if m.role != "system"
        ]
        payload: dict = {
            "model": model,
            "max_tokens": 2048,
            "messages": body_messages,
        }
        if system:
            payload["system"] = system
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=120.0, trust_env=True) as client:
            resp = await client.post(f"{self.base_url}/v1/messages", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        parts = data.get("content") or []
        text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
        usage = data.get("usage") or {}
        return LLMResult(
            content=text,
            prompt_tokens=int(usage.get("input_tokens") or 0),
            completion_tokens=int(usage.get("output_tokens") or 0),
            provider=self.name,
            model=model,
        )

    async def embed(self, *, task: str, texts: list[str]) -> EmbedResult:
        vectors = mock_embed_vectors(texts, self.dim)
        return EmbedResult(
            vectors=vectors,
            prompt_tokens=sum(max(1, len(t) // 4) for t in texts),
            provider=self.name,
            model="mock-embed-for-anthropic",
            dim=self.dim,
        )
