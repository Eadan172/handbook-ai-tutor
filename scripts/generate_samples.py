#!/usr/bin/env python3
"""Generate a tiny sample PDF and MP4 for local demos."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.utils.sample_pdf import make_text_pdf  # noqa: E402

SAMPLES = ROOT / "test-outputs" / "inputs"
SAMPLES.mkdir(parents=True, exist_ok=True)

PDF_TEXT = (
    "Photosynthesis converts light energy into chemical energy. "
    "Chlorophyll in chloroplasts captures photons. "
    "Water and carbon dioxide become glucose and oxygen. "
    "The Calvin cycle fixes carbon into sugars."
)


def write_pdf() -> Path:
    path = SAMPLES / "photosynthesis.pdf"
    path.write_bytes(make_text_pdf(PDF_TEXT, title="Photosynthesis"))
    return path


def write_mp4() -> Path:
    path = SAMPLES / "lesson.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:d=3",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono:d=3",
            "-shortest",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


if __name__ == "__main__":
    pdf = write_pdf()
    print(f"wrote {pdf}")
    try:
        mp4 = write_mp4()
        print(f"wrote {mp4}")
    except Exception as exc:
        print(f"mp4 skipped: {exc}")
