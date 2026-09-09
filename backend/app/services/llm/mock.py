from __future__ import annotations

import hashlib
import json
import math
import re

from app.core.config import get_settings
from app.services.llm.base import ChatMessage, EmbedResult, LLMProvider, LLMResult


def _tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def mock_embed_vectors(texts: list[str], dim: int) -> list[list[float]]:
    vectors: list[list[float]] = []
    for text in texts:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:8], "little")
        vec: list[float] = []
        state = seed
        for i in range(dim):
            state = (state * 1103515245 + 12345 + i) & 0x7FFFFFFF
            vec.append(((state % 10000) / 5000.0) - 1.0)
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        vectors.append([x / norm for x in vec])
    return vectors


class MockProvider(LLMProvider):
    name = "mock"

    def __init__(self, model: str = "mock-llm", embed_model: str = "mock-embed") -> None:
        self.model = model
        self.embed_model = embed_model
        self.dim = get_settings().embedding_dim

    async def complete(
        self,
        *,
        task: str,
        messages: list[ChatMessage],
        json_mode: bool = False,
    ) -> LLMResult:
        user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        content = self._content_for_task(task, user)
        prompt = "\n".join(m.content for m in messages)
        return LLMResult(
            content=content,
            prompt_tokens=_tokens(prompt),
            completion_tokens=_tokens(content),
            provider=self.name,
            model=self.model,
        )

    async def embed(self, *, task: str, texts: list[str]) -> EmbedResult:
        vectors = mock_embed_vectors(texts, self.dim)
        return EmbedResult(
            vectors=vectors,
            prompt_tokens=sum(_tokens(t) for t in texts),
            provider=self.name,
            model=self.embed_model,
            dim=self.dim,
        )

    def _content_for_task(self, task: str, user: str) -> str:
        ids = re.findall(r"chunk_id=([0-9a-f-]{36})", user, flags=re.I)
        first_ids = ids[:4] if ids else []
        snippet = user[:400].replace("\n", " ")

        if task == "summarize":
            return json.dumps(
                {
                    "title": "Study notes (mock)",
                    "overview": (
                        "This is a mock summary generated without calling a remote LLM. "
                        f"The source discusses: {snippet[:240] or 'uploaded learning material'}."
                    ),
                    "outline": ["Introduction", "Core ideas", "Practice & recap"],
                }
            )
        if task == "extract_knowledge":
            points = []
            labels = ["Core concept", "Key process", "Common pitfall", "Exam focus"]
            for i, label in enumerate(labels):
                points.append(
                    {
                        "title": f"{label} {i + 1}",
                        "summary": f"Mock knowledge point about: {snippet[:120] or 'the source'}.",
                        "key_terms": [f"term-{i + 1}a", f"term-{i + 1}b"],
                        "chunk_ids": first_ids[i : i + 1],
                    }
                )
            return json.dumps({"points": points})
        if task == "quiz_generate":
            questions = []
            for i in range(4):
                questions.append(
                    {
                        "question": f"Mock question {i + 1}: what is a main idea in this source?",
                        "options": [
                            "A concept grounded in the uploaded material",
                            "An unrelated historical date",
                            "A random programming trivia fact",
                            "None of the source content",
                        ],
                        "correct_index": 0,
                        "explanation": "The mock quiz always treats option A as grounded in the source.",
                        "chunk_ids": first_ids[:1],
                    }
                )
            return json.dumps({"title": "Practice quiz (mock)", "questions": questions})
        if task == "segment_summarize":
            return json.dumps(
                {
                    "start_time": 0.0,
                    "end_time": 15.0,
                    "summary": f"Mock segment summary: {snippet[:180] or 'spoken content'}",
                    "key_points": ["Point A", "Point B"],
                }
            )
        if task == "tutor":
            cite = first_ids[:2]
            return json.dumps(
                {
                    "reply": (
                        "Let's reason from the source together. Based on the retrieved excerpts, "
                        "the material focuses on the uploaded content rather than outside trivia. "
                        "What part still feels unclear — the definition, or how you would apply it?"
                    ),
                    "citation_chunk_ids": cite,
                }
            )
        return json.dumps({"reply": f"Mock response for task={task}", "citation_chunk_ids": first_ids[:1]})
