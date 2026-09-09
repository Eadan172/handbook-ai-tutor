from __future__ import annotations

from io import BytesIO
from pathlib import Path

SAMPLE_PDF_TEXT = (
    "Photosynthesis converts light energy into chemical energy. "
    "Chlorophyll in chloroplasts captures photons. "
    "The Calvin cycle fixes carbon dioxide into glucose."
)


def minimal_pdf_bytes(text: str = SAMPLE_PDF_TEXT) -> bytes:
    # Keep the stream ASCII so the /Length matches.
    safe = "".join(ch if 32 <= ord(ch) < 127 else " " for ch in text)[:200]
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
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000306 00000 n 
0000000400 00000 n 
trailer << /Size 6 /Root 1 0 R >>
startxref
490
%%EOF
"""
    return pdf.encode("latin-1")


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
