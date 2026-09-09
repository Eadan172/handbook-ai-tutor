from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader


@dataclass
class ParsedPage:
    page_number: int
    text: str


def parse_pdf(data: bytes) -> list[ParsedPage]:
    reader = PdfReader(BytesIO(data))
    pages: list[ParsedPage] = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            text = f"[PDF page {i} contained no extractable text]"
        pages.append(ParsedPage(page_number=i, text=text))
    if not pages:
        pages.append(ParsedPage(page_number=1, text="[Empty PDF]"))
    return pages
