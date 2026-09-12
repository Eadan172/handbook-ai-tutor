from __future__ import annotations

from pathlib import Path

import httpx

from app.core.config import get_settings
from app.services.stt import STTProvider, TranscriptSegment, probe_duration


class STTConfigError(RuntimeError):
    """Missing key or adapter misconfigured — never fall back to mock."""


_PLACEHOLDERS = {"", "your_key_here", "changeme", "xxx", "todo", "replace-me"}


class SiliconFlowSTT(STTProvider):
    """Cloud ASR via POST /v1/audio/transcriptions (file + model only)."""

    name = "siliconflow"

    def __init__(self) -> None:
        import os

        settings = get_settings()
        key = (os.environ.get("SILICONFLOW_API_KEY") or "").strip()
        if not key or key.lower() in _PLACEHOLDERS:
            raise STTConfigError(
                "STT_PROVIDER=siliconflow 但 SILICONFLOW_API_KEY 为空。"
                "请在 .env 填入密钥后重新导入，不会回退到 mock。"
            )
        self._key = key
        self._model = (getattr(settings, "stt_siliconflow_model", None) or "FunAudioLLM/SenseVoiceSmall").strip()
        base = (getattr(settings, "stt_siliconflow_base_url", None) or "https://api.siliconflow.cn/v1").rstrip("/")
        self._url = f"{base}/audio/transcriptions"

    async def transcribe(self, audio_path: Path) -> list[TranscriptSegment]:
        duration = await probe_duration(audio_path)
        filename = audio_path.name or "audio.wav"
        mime = "audio/wav" if filename.lower().endswith(".wav") else "application/octet-stream"
        data = audio_path.read_bytes()
        # Official API: multipart file + model only. language / response_format → 400.
        async with httpx.AsyncClient(timeout=360.0, trust_env=True) as client:
            resp = await client.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}"},
                files={"file": (filename, data, mime)},
                data={"model": self._model},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"SiliconFlow STT {resp.status_code}: {(resp.text or '')[:400]}")
        payload = resp.json() if resp.content else {}
        raw_segs = payload.get("segments") or []
        out: list[TranscriptSegment] = []
        for seg in raw_segs:
            if not isinstance(seg, dict):
                continue
            text = str(seg.get("text") or "").strip()
            if not text:
                continue
            out.append(
                TranscriptSegment(
                    start=float(seg.get("start") or 0.0),
                    end=float(seg.get("end") or duration or 0.0),
                    text=text,
                )
            )
        if out:
            return out
        text = str(payload.get("text") or "").strip()
        if not text:
            raise RuntimeError("SiliconFlow STT 返回空文本（不是 mock）。请检查音频是否有人声。")
        return [TranscriptSegment(start=0.0, end=max(float(duration or 0.0), 0.1), text=text)]
