from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, Field


class TextPart(BaseModel):
    """A plain text block inside a multimodal message."""

    type: Literal["text"] = "text"
    text: str


class ImagePart(BaseModel):
    """An inline image carried as a data URL.

    Data URLs keep the whole pipeline self-contained: no public bucket, no signed
    URL that expires mid-request, no extra round trip to the storage backend.
    """

    type: Literal["image_url"] = "image_url"
    data_url: str
    mime: str = "image/png"
    detail: str = "auto"

    @property
    def base64_payload(self) -> str:
        """The raw base64 body, without the `data:<mime>;base64,` prefix."""
        _, _, payload = self.data_url.partition(",")
        return payload or self.data_url


ContentPart = TextPart | ImagePart


class ChatMessage(BaseModel):
    """One chat turn. `content` is either plain text or a list of content parts.

    Text-only callers keep passing a plain string; multimodal callers pass
    `[TextPart(...), ImagePart(...)]`. Every provider serialises this into its own
    wire format, so business code never touches a vendor schema.
    """

    role: str
    content: str | list[ContentPart] = ""

    # ---------------------------------------------------------------- helpers

    def text(self) -> str:
        """Flatten to plain text. Images become a short marker so logs stay readable."""
        if isinstance(self.content, str):
            return self.content
        chunks: list[str] = []
        for part in self.content:
            if isinstance(part, TextPart):
                chunks.append(part.text)
            else:
                chunks.append(f"[image {part.mime}]")
        return "\n".join(chunks)

    def images(self) -> list[ImagePart]:
        if isinstance(self.content, str):
            return []
        return [part for part in self.content if isinstance(part, ImagePart)]

    @classmethod
    def user_text(cls, text: str) -> "ChatMessage":
        return cls(role="user", content=text)

    @classmethod
    def user_with_image(cls, text: str, image: ImagePart) -> "ChatMessage":
        return cls(role="user", content=[TextPart(text=text), image])


def message_text(messages: list["ChatMessage"]) -> str:
    """All messages flattened to text — used for token estimates and logging."""
    return "\n".join(m.text() for m in messages)


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

    def model_for(self, task: str) -> str:
        """Resolve the concrete model name this provider would use for a task."""
        models = getattr(self, "models", None) or {}
        return str(models.get(task) or models.get("default") or getattr(self, "model", "unknown"))

    def supports_vision(self) -> bool:
        """True when this provider has a model configured for `transcribe_image`."""
        models = getattr(self, "models", None) or {}
        return bool(models.get("transcribe_image"))

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
