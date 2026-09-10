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

    # 长音频按此长度切段再逐段识别。faster-whisper 会对整段音频一次性构建
    # log-mel 特征（25 分钟 ≈ 220+ MB float32），在小内存机器上直接 OOM；
    # 切段后峰值内存随段长线性下降，同时段间用时间偏移拼回全局时间戳。
    CHUNK_SECONDS = 300.0

    async def transcribe(self, audio_path: Path) -> list[TranscriptSegment]:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("faster-whisper is not installed. Use STT_PROVIDER=mock.") from exc

        settings = get_settings()
        model_size = settings.stt_whisper_model
        use_vad = settings.stt_whisper_vad

        def _resolve_model() -> str:
            """Prefer a repo-local model dir (tools/whisper-<size>) when present —
            HuggingFace 在本网络不可达，模型可经 ModelScope 离线放置。否则按
            模型名交给 faster-whisper 走 HF 下载。"""
            from app.core.config import REPO_ROOT

            local = REPO_ROOT / "tools" / f"whisper-{model_size}"
            if (local / "model.bin").is_file() and (local / "model.bin").stat().st_size > 1_000_000:
                return str(local)
            return model_size

        def _transcribe_one(model, wav: Path, offset: float) -> list[TranscriptSegment]:
            # language=None → auto-detect：中文讲课夹杂法语/英语朗读时逐段识别，
            # multilingual 模型天然支持 code-switching，无需专门微调。
            segs, _info = model.transcribe(
                str(wav),
                vad_filter=use_vad,
                beam_size=5,
            )
            out: list[TranscriptSegment] = []
            for seg in segs:
                out.append(
                    TranscriptSegment(
                        start=float(seg.start) + offset,
                        end=float(seg.end) + offset,
                        text=seg.text.strip(),
                    )
                )
            return out

        def _run() -> list[TranscriptSegment]:
            model = WhisperModel(_resolve_model(), device="cpu", compute_type="int8")
            duration = _duration_sync(audio_path)
            if duration <= self.CHUNK_SECONDS:
                return _transcribe_one(model, audio_path, 0.0)

            chunks = _split_wav_sync(audio_path, self.CHUNK_SECONDS)
            out: list[TranscriptSegment] = []
            try:
                for wav, offset in chunks:
                    out.extend(_transcribe_one(model, wav, offset))
            finally:
                for wav, _ in chunks:
                    wav.unlink(missing_ok=True)
            return out or [
                TranscriptSegment(start=0, end=1, text="[empty transcription]")
            ]

        from asyncio import to_thread

        return await to_thread(_run)


def _duration_sync(path: Path) -> float:
    """Blocking ffprobe duration probe (called inside the whisper worker thread)."""
    import subprocess

    proc = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
    )
    try:
        return float(proc.stdout.decode().strip() or "0")
    except ValueError:
        return 0.0


def _split_wav_sync(path: Path, chunk_seconds: float) -> list[tuple[Path, float]]:
    """Split a wav into chunk_seconds-long pieces with ffmpeg; returns
    [(chunk_path, offset_seconds)] in order. Pieces land next to the source in
    the same temp dir, so the caller's cleanup removes them with it."""
    import subprocess

    pattern = path.with_name("chunk_%05d.wav")
    proc = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(path),
            "-f", "segment",
            "-segment_time", str(int(chunk_seconds)),
            "-c", "copy",
            str(pattern),
        ],
        capture_output=True,
    )
    if proc.returncode != 0:
        # Fall back to the whole file rather than failing the lesson.
        return [(path, 0.0)]
    pieces = sorted(path.parent.glob("chunk_*.wav"))
    return [(p, i * chunk_seconds) for i, p in enumerate(pieces)]


def get_stt() -> STTProvider:
    if get_settings().stt_provider == "faster_whisper":
        return FasterWhisperSTT()
    return MockSTT()
