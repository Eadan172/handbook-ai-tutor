from __future__ import annotations

import asyncio
import shutil
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


class STTProvider(ABC):
    name: str

    @abstractmethod
    async def transcribe(self, audio_path: Path) -> list[TranscriptSegment]:
        raise NotImplementedError


async def probe_duration(path: Path) -> float:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    try:
        return float(stdout.decode().strip() or "0")
    except ValueError:
        return 0.0


async def extract_audio(video_bytes: bytes, suffix: str = ".mp4") -> tuple[Path, Path, float]:
    """Write video to a temp file, extract WAV via FFmpeg, return (workdir, wav, duration)."""
    work = Path(tempfile.mkdtemp(prefix="tutor-video-"))
    video_path = work / f"source{suffix}"
    wav_path = work / "audio.wav"
    video_path.write_bytes(video_bytes)
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(wav_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not wav_path.exists():
        shutil.rmtree(work, ignore_errors=True)
        raise RuntimeError(f"FFmpeg failed: {stderr.decode()[-500:]}")
    duration = await probe_duration(wav_path)
    if duration <= 0:
        duration = await probe_duration(video_path)
    return work, wav_path, duration


class MockSTT(STTProvider):
    """Offline/dev STT so the video loop works without a GPU or Whisper weights."""

    name = "mock"

    MOCK_LESSON = [
        "Welcome to this short lesson on photosynthesis in green plants.",
        "Light energy is captured by chlorophyll inside chloroplasts.",
        "Water and carbon dioxide are converted into glucose and oxygen.",
        "The light-dependent reactions produce ATP and NADPH.",
        "The Calvin cycle then fixes carbon into sugars the plant can store.",
    ]

    async def transcribe(self, audio_path: Path) -> list[TranscriptSegment]:
        duration = await probe_duration(audio_path)
        if duration <= 0:
            duration = float(len(self.MOCK_LESSON) * 5)
        n = len(self.MOCK_LESSON)
        window = duration / n
        segments: list[TranscriptSegment] = []
        for i, sentence in enumerate(self.MOCK_LESSON):
            start = round(i * window, 2)
            end = round(min(duration, (i + 1) * window), 2)
            segments.append(TranscriptSegment(start=start, end=end, text=sentence))
        return segments


class FasterWhisperSTT(STTProvider):
    name = "faster_whisper"

    async def transcribe(self, audio_path: Path) -> list[TranscriptSegment]:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("faster-whisper is not installed. Use STT_PROVIDER=mock.") from exc

        def _run() -> list[TranscriptSegment]:
            model = WhisperModel("base", device="cpu", compute_type="int8")
            segs, _ = model.transcribe(str(audio_path))
            out: list[TranscriptSegment] = []
            for seg in segs:
                out.append(TranscriptSegment(start=float(seg.start), end=float(seg.end), text=seg.text.strip()))
            return out or MockSTT.MOCK_LESSON and [
                TranscriptSegment(start=0, end=1, text="[empty transcription]")
            ]

        from asyncio import to_thread

        return await to_thread(_run)


def get_stt() -> STTProvider:
    if get_settings().stt_provider == "faster_whisper":
        return FasterWhisperSTT()
    return MockSTT()
