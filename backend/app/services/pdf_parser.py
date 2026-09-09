from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError


@dataclass
class ParsedPage:
    page_number: int
    text: str


def parse_pdf(data: bytes) -> list[ParsedPage]:
    try:
        reader = PdfReader(BytesIO(data), strict=False)
        pages: list[ParsedPage] = []
        for i, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                text = f"[PDF page {i} contained no extractable text]"
            pages.append(ParsedPage(page_number=i, text=text))
        if pages:
            return pages
    except (PdfReadError, Exception):
        extracted = _printable_streams(data)
        if extracted:
            return [ParsedPage(page_number=1, text=extracted)]
        raise
    return [ParsedPage(page_number=1, text="[Empty PDF]")]


def _printable_streams(data: bytes) -> str:
    chunks: list[str] = []
    lower = data.lower()
    start = 0
    while True:
        i = lower.find(b"stream", start)
        if i < 0:
            break
        j = lower.find(b"endstream", i)
        if j < 0:
            break
        raw = data[i + 6 : j]
        text = "".join(chr(b) if 32 <= b < 127 else " " for b in raw)
        text = " ".join(text.split())
        if len(text) > 20:
            chunks.append(text)
        start = j + 9
    return "\n".join(chunks)[:8000]
