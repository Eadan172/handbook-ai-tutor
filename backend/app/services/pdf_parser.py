"""PDF text-layer extraction, plus the embedded images needed for OCR.

A PDF page is one of three things:
  1. real text       -> use it, it is free and exact
  2. one big image   -> a scan / photo of a page; needs OCR
  3. neither         -> genuinely empty page

The previous version collapsed cases 2 and 3 into the literal string
"[PDF page N contained no extractable text]" and then fed that *placeholder* to
the LLM as if it were the document. The summary came back saying no source
material was available, knowledge points were empty, and quiz generation produced
hollow questions — all while the source reported status "ready". Pages are now
marked as textless so the pipeline can OCR them or fail loudly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

logger = logging.getLogger("app.pdf")

# A document needs at least this many non-whitespace characters to count as
# "has a text layer". Below it, OCR is the only way to read the content.
MIN_USABLE_CHARS = 24

# Embedded images smaller than this are almost always logos, rules or icons.
MIN_IMAGE_BYTES = 4096


@dataclass
class PdfPage:
    page_number: int
    text: str = ""
    image: bytes | None = None

    @property
    def has_text(self) -> bool:
        return len(self.text.strip()) >= 2


def parse_pdf(data: bytes, *, extract_images: bool = False) -> list[PdfPage]:
    """Split a PDF into pages, optionally pulling each text-less page's image out.

    Set `extract_images=True` only when the text layer is missing: decoding every
    embedded image in a 300-page text PDF would be pure waste.
    """
    try:
        reader = PdfReader(BytesIO(data), strict=False)
    except Exception:
        # Corrupt / non-standard container: fall back to scanning raw streams for
        # anything printable, which recovers some hand-built PDFs.
        extracted = _printable_streams(data)
        if extracted:
            return [PdfPage(page_number=1, text=extracted)]
        raise

    pages: list[PdfPage] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception as exc:  # a single broken page must not kill the document
            logger.warning("page %s: text extraction failed (%s)", index, exc)
            text = ""
        page_obj = PdfPage(page_number=index, text=text)
        if extract_images and not page_obj.has_text:
            page_obj.image = _first_page_image(page, index)
        pages.append(page_obj)

    if not pages and data:
        extracted = _printable_streams(data)
        if extracted:
            return [PdfPage(page_number=1, text=extracted)]
    return pages


def _first_page_image(page, page_number: int) -> bytes | None:
    """Decode the largest embedded image on a page, if any.

    Scanned pages are normally a single full-bleed image. Vector-only pages (and
    some CCITT/JBIG2 scans Pillow cannot decode) yield None, which the caller
    treats as "this page is genuinely unreadable" rather than "empty document".
    """
    try:
        images = list(page.images)
    except Exception as exc:
        logger.warning("page %s: cannot read embedded images (%s)", page_number, exc)
        return None
    best: bytes | None = None
    for item in images:
        try:
            raw = item.data
        except Exception:
            continue
        if raw and len(raw) >= MIN_IMAGE_BYTES and (best is None or len(raw) > len(best)):
            best = raw
    if best is None:
        # Everything was tiny; keep the largest anyway so the page is not silently
        # dropped when the "scan" is a small crop.
        for item in images:
            try:
                raw = item.data
            except Exception:
                continue
            if raw and (best is None or len(raw) > len(best)):
                best = raw
    return best


def document_text_length(pages: list[PdfPage]) -> int:
    return sum(len(page.text.strip()) for page in pages)


def looks_textless(pages: list[PdfPage]) -> bool:
    """True when there is not enough real text for summarisation to be meaningful."""
    return document_text_length(pages) < MIN_USABLE_CHARS


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


__all__ = [
    "MIN_USABLE_CHARS",
    "PdfPage",
    "PdfReadError",
    "document_text_length",
    "looks_textless",
    "parse_pdf",
]
