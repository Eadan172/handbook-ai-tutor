from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str


class LLMResult(BaseModel):
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    provider: str
    model: str


class EmbedResult(BaseModel):
    vectors: list[list[float]]
    prompt_tokens: int = 0
    provider: str
    model: str
    dim: int = Field(default=1536)


class LLMProvider(ABC):
    """Vendor-agnostic LLM + embedding provider. Business code never imports a vendor SDK."""

    name: str

    @abstractmethod
    async def complete(
        self,
        *,
        task: str,
        messages: list[ChatMessage],
        json_mode: bool = False,
    ) -> LLMResult:
        raise NotImplementedError

    @abstractmethod
    async def embed(self, *, task: str, texts: list[str]) -> EmbedResult:
        raise NotImplementedError
