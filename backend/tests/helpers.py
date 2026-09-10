from __future__ import annotations

from pathlib import Path

from app.utils.sample_pdf import make_text_pdf

SAMPLE_PDF_TEXT = (
    "Photosynthesis converts light energy into chemical energy. "
    "Chlorophyll in chloroplasts captures photons. "
    "The Calvin cycle fixes carbon dioxide into glucose."
)


def minimal_pdf_bytes(text: str = SAMPLE_PDF_TEXT) -> bytes:
    return make_text_pdf(text)


def tiny_mp4_bytes() -> bytes:
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "clip.mp4"
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=160x120:d=2",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono:d=2",
            "-shortest",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            str(out),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return out.read_bytes()
