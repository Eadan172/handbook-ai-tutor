from __future__ import annotations

import hashlib
import json
import math
import re

from app.core.config import get_settings
from app.services.llm.base import ChatMessage, EmbedResult, LLMProvider, LLMResult, message_text


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

    def model_for(self, task: str) -> str:
        return self.embed_model if task == "embed" else self.model

    async def complete(
        self,
        *,
        task: str,
        messages: list[ChatMessage],
        json_mode: bool = False,
    ) -> LLMResult:
        user = next((m.text() for m in reversed(messages) if m.role == "user"), "")
        content = self._content_for_task(task, user, messages)
        prompt = message_text(messages)
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

    def _content_for_task(self, task: str, user: str, messages: list[ChatMessage] | None = None) -> str:
        ids = re.findall(r"chunk_id=([0-9a-f-]{36})", user, flags=re.I)
        first_ids = ids[:4] if ids else []
        snippet = user[:400].replace("\n", " ")

        if task == "transcribe_image":
            # Deliberately honest: the mock cannot read pixels. It emits a clearly
            # labelled placeholder so the rest of the pipeline stays testable and
            # nobody mistakes this for a real transcription.
            images = [img for m in (messages or []) for img in m.images()]
            return json.dumps(
                {
                    "text": (
                        "[mock transcription] No real OCR ran. "
                        f"{len(images)} image(s) received. "
                        "Configure OCR_PROVIDER=rapidocr for offline OCR, or put a "
                        "vision-capable API key in .env (e.g. DASHSCOPE_API_KEY) and set "
                        "LLM_PROVIDER_VISION=dashscope."
                    ),
                    "language": "unknown",
                    "is_mock": True,
                }
            )
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
            # Honour [section=...] headers when present so coverage tests (and
            # per-section generate) land questions on real chapter titles.
            found_sections = re.findall(r"\[section=([^\]]+)\]", user)
            uniq_sections = list(dict.fromkeys(s.strip() for s in found_sections if s.strip()))
            # v2 shape: sections + mixed question types
            questions = []
            default_plan = [
                ("Section 1 — Overview", "choice"),
                ("Section 1 — Overview", "choice"),
                ("Section 2 — Key ideas", "choice"),
                ("Section 2 — Key ideas", "translation"),
                ("Section 3 — Practice", "writing"),
                ("Section 3 — Practice", "speaking"),
            ]
            if uniq_sections:
                type_cycle = ["choice", "choice", "translation", "writing", "speaking"]
                plan = [
                    (section, type_cycle[i % len(type_cycle)])
                    for i, section in enumerate(uniq_sections)
                ]
                # Keep mixed types on a single-section call (per-section generate).
                if len(plan) == 1:
                    plan = [
                        (uniq_sections[0], "choice"),
                        (uniq_sections[0], "writing"),
                    ]
            else:
                plan = default_plan
            for i, (section, qtype) in enumerate(plan):
                row = {
                    "section_title": section,
                    "question_type": qtype,
                    "question": f"Mock question {i + 1}: what is a main idea in this source?",
                    "options": [
                        "A concept grounded in the uploaded material",
                        "An unrelated historical date",
                        "A random programming trivia fact",
                        "None of the source content",
                    ]
                    if qtype == "choice"
                    else [],
                    "correct_index": 0,
                    "reference_answer": "The mock reference answer is grounded in the uploaded material.",
                    "rubric": "Must refer to the uploaded material.",
                    "instructions": "Pick one option." if qtype == "choice" else "Type your answer below.",
                    "explanation": "The mock quiz always treats option A as grounded in the source.",
                    "chunk_ids": first_ids[:1],
                }
                if qtype == "translation":
                    row["question"] = "Translate this sentence into your target language: 'The Calvin cycle fixes carbon into sugars.'"
                    row["instructions"] = "Type your translation."
                elif qtype == "writing":
                    row["question"] = "Write a short paragraph (80-120 words) explaining the main process in this source."
                    row["instructions"] = "Type your paragraph."
                elif qtype == "speaking":
                    row["question"] = "Say aloud a 30-second explanation of this source, then type what you said."
                    row["instructions"] = "Type the script of what you would say."
                questions.append(row)
            return json.dumps({"title": "Practice quiz (mock)", "questions": questions})
        if task == "quiz_explain":
            # Echo one verdict per question so the marking pass always completes.
            ordinals = [int(x) for x in re.findall(r"ordinal=(\d+)", user)] or [0]
            results = []
            for ordinal in ordinals:
                results.append(
                    {
                        "ordinal": ordinal,
                        "verdict": "correct",
                        "score": 1.0,
                        "explanation": (
                            f"Mock explanation for question {ordinal + 1}: the answer matches the "
                            "reference grounded in the uploaded material."
                        ),
                    }
                )
            return json.dumps({"results": results})
        if task == "notes_generate":
            return json.dumps(
                {
                    "notes": [
                        {
                            "title": "Mock study note",
                            "anchor": "p.1",
                            "content": (
                                "Key ideas (mock)\n\n"
                                f"- {snippet[:160] or 'The source discusses the uploaded material.'}\n"
                                "- Review the relationships between the core concepts.\n\n"
                                "Self-check: can you explain the main process in your own words?"
                            ),
                        }
                    ]
                }
            )
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
