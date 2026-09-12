from __future__ import annotations

from pathlib import Path

import pytest

from app.services.stt import TranscriptSegment, transcribe_audio_resilient


class FlakySTT:
    name = "flaky"

    def __init__(self) -> None:
        self.calls = 0

    async def transcribe(self, audio_path: Path) -> list[TranscriptSegment]:
        self.calls += 1
        # Fail the first attempt of the second window, then succeed.
        if self.calls == 2:
            raise RuntimeError("segment boom")
        return [TranscriptSegment(start=0.0, end=1.0, text=f"ok-{self.calls}")]


class AlwaysFailSTT:
    name = "always_fail"

    async def transcribe(self, audio_path: Path) -> list[TranscriptSegment]:
        raise RuntimeError("hard fail")


@pytest.mark.asyncio
async def test_failed_stt_window_is_retried_independently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"fake")
    piece_a = tmp_path / "a.wav"
    piece_b = tmp_path / "b.wav"
    piece_a.write_bytes(b"a")
    piece_b.write_bytes(b"b")

    async def fake_probe(_path: Path) -> float:
        return 600.0

    def fake_split(_path: Path, _seconds: float) -> list[tuple[Path, float]]:
        return [(piece_a, 0.0), (piece_b, 300.0)]

    monkeypatch.setattr("app.services.stt.probe_duration", fake_probe)
    monkeypatch.setattr("app.services.stt._split_wav_sync", fake_split)

    stt = FlakySTT()
    result = await transcribe_audio_resilient(stt, wav, chunk_seconds=300.0, attempts=3)
    assert result.failed_windows == 0
    assert result.total_windows == 2
    assert stt.calls == 3  # window 1 ok, window 2 fail then ok
    texts = [s.text for s in result.segments]
    assert "ok-1" in texts
    assert "ok-3" in texts
    assert all("failed" not in t for t in texts)


@pytest.mark.asyncio
async def test_exhausted_stt_window_is_labelled_not_fatal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"fake")

    async def fake_probe(_path: Path) -> float:
        return 10.0

    monkeypatch.setattr("app.services.stt.probe_duration", fake_probe)

    result = await transcribe_audio_resilient(AlwaysFailSTT(), wav, chunk_seconds=300.0, attempts=2)
    assert result.failed_windows == 1
    assert result.segments
    assert "failed after" in result.segments[0].text
    assert "failed after retry" in result.note or "failed" in result.note
