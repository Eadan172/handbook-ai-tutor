from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.ocr import OcrPage, OcrResult
from app.services.pipeline import IngestPipeline
from app.utils.text import normalise_text


def test_common_chinese_mojibake_is_repaired_conservatively() -> None:
    assert normalise_text("妯″瀷璺敱璇婃柇") == "模型路由诊断"
    assert normalise_text("正常的中文 Q&A") == "正常的中文 Q&A"


def test_env_and_prompts_are_valid_utf8() -> None:
    root = Path(__file__).resolve().parents[2]
    env_text = (root / ".env.example").read_text(encoding="utf-8")
    quiz_prompt = (root / "backend/app/prompts/quiz_generate.v3.txt").read_text(encoding="utf-8")
    assert "模型路由诊断" in env_text
    assert "妯″瀷" not in env_text
    assert "画面/PPT/板书" in quiz_prompt
    assert "course scheduling" in quiz_prompt


@pytest.mark.asyncio
async def test_video_visuals_become_timestamped_knowledge_segments(monkeypatch) -> None:
    async def fake_frames(_path, _duration):
        return [(0.0, b"first"), (30.0, b"same"), (60.0, b"third")]

    class FakeOcr:
        async def transcribe(self, _images, **_kwargs):
            return OcrResult(
                pages=[
                    OcrPage(1, "光合作用：光能转化为化学能"),
                    OcrPage(2, "光合作用：光能转化为化学能"),
                    OcrPage(3, "卡尔文循环固定二氧化碳"),
                ],
                provider="test-ocr",
                model="test-model",
            )

    monkeypatch.setattr("app.services.pipeline.extract_video_frames", fake_frames)
    monkeypatch.setattr("app.services.pipeline.get_ocr", lambda _router: FakeOcr())

    pipeline = object.__new__(IngestPipeline)
    pipeline.router = object()
    source = SimpleNamespace(user_id=uuid4(), id=uuid4())
    segments, note = await pipeline._video_visual_segments(
        source, Path("lesson.mp4"), 90.0
    )

    assert [(s.start, s.text) for s in segments] == [
        (0.0, "[画面/PPT/板书] 光合作用：光能转化为化学能"),
        (60.0, "[画面/PPT/板书] 卡尔文循环固定二氧化碳"),
    ]
    assert "2 visual frame(s)" in note
