#!/usr/bin/env python3
"""Generate a tiny sample PDF and MP4 for local demos."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
SAMPLES.mkdir(exist_ok=True)

PDF_TEXT = (
    "Photosynthesis converts light energy into chemical energy. "
    "Chlorophyll in chloroplasts captures photons. "
    "Water and carbon dioxide become glucose and oxygen. "
    "The Calvin cycle fixes carbon into sugars."
)


def write_pdf() -> Path:
    safe = PDF_TEXT[:180]
    stream = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET\n"
    length = len(stream.encode("ascii"))
    pdf = f"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj
4 0 obj << /Length {length} >> stream
{stream}endstream
endobj
5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
trailer << /Size 6 /Root 1 0 R >>
%%EOF
"""
    path = SAMPLES / "photosynthesis.pdf"
    path.write_bytes(pdf.encode("latin-1"))
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
