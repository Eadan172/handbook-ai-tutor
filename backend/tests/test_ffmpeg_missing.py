from __future__ import annotations

from pathlib import Path

import pytest

from app.core.ffmpeg import FFmpegMissing, resolve_ffmpeg_tool


def test_missing_ffmpeg_names_tools_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("FFMPEG_DIR", raising=False)
    monkeypatch.delenv("FFMPEG_BIN_DIR", raising=False)
    monkeypatch.setattr("app.core.ffmpeg.bundled_bin_dir", lambda: tmp_path / "missing-bin")
    monkeypatch.setattr("app.core.ffmpeg.shutil.which", lambda _name: None)

    with pytest.raises(FFmpegMissing) as exc:
        resolve_ffmpeg_tool("ffmpeg")
    message = str(exc.value)
    assert "tools" in message and "ffmpeg" in message
    assert "bin" in message


@pytest.mark.asyncio
async def test_extract_audio_raises_when_ffmpeg_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("FFMPEG_DIR", raising=False)
    monkeypatch.setattr("app.core.ffmpeg.bundled_bin_dir", lambda: tmp_path / "missing-bin")
    monkeypatch.setattr("app.core.ffmpeg.shutil.which", lambda _name: None)

    from app.services.stt import extract_audio

    with pytest.raises(FFmpegMissing):
        await extract_audio(b"not-a-video")
