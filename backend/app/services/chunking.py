from __future__ import annotations

from dataclasses import dataclass

from app.services.layout import (
    ATOMIC_TYPES,
    BODY,
    CAPTION,
    HEADING,
    OUTLINE,
    RETRIEVABLE_TYPES,
    TYPE_LABELS,
    Block,
    DocumentLayout,
    outline_text,
)


@dataclass
class RawChunk:
    content: str
    page_number: int | None = None
    start_time: float | None = None
    end_time: float | None = None
    locator: str | None = None
    #: Page as printed on the paper, when the running heads revealed the offset.
    printed_page: int | None = None
    #: "第3章 指令级并行 > 3.2 分支预测", empty when the document has no headings.
    section_title: str = ""
    content_type: str = BODY
    heading_level: int | None = None


def _split_window(text: str, size: int = 900, overlap: int = 120) -> list[str]:
    text = " ".join(text.split())
    if len(text) <= size:
        return [text] if text else []
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        parts.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return parts


def _split_paragraphs(text: str, size: int, overlap: int) -> list[str]:
    """Split on blank lines first, then by window.

    A paragraph is the smallest unit a reader would quote, so keeping its edges
    intact matters more than hitting an exact chunk size. Only paragraphs longer
    than ``size`` are windowed, and then with overlap so a fact straddling the
    cut is still retrievable from one of the two halves.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    parts: list[str] = []
    buffer = ""
    for block in blocks:
        if len(block) > size:
            if buffer:
                parts.extend(_split_window(buffer, size, overlap))
                buffer = ""
            parts.extend(_split_window(block, size, overlap))
            continue
        candidate = f"{buffer}\n\n{block}" if buffer else block
        if len(candidate) > size:
            if buffer:
                parts.extend(_split_window(buffer, size, overlap))
            buffer = block
        else:
            buffer = candidate
    if buffer:
        parts.extend(_split_window(buffer, size, overlap))
    return parts


def _locator(page_number: int | None, printed_page: int | None, section: str, kind: str) -> str:
    """Human-facing pointer. Prefers the printed page, since that is what the
    learner sees on the paper and what they will type into a question."""
    bits: list[str] = []
    if printed_page is not None:
        bits.append(f"书内 p.{printed_page}")
        if page_number is not None and page_number != printed_page:
            bits.append(f"PDF p.{page_number}")
    elif page_number is not None:
        bits.append(f"p.{page_number}")
    label = TYPE_LABELS.get(kind, kind)
    if kind not in (BODY, HEADING):
        bits.append(label)
    return " · ".join(bits)


def chunk_pages(pages: list[tuple[int, str]]) -> list[RawChunk]:
    """Legacy path: page -> text, no structure. Kept for callers that only have
    plain text (and for the corrupt-PDF fallback)."""
    chunks: list[RawChunk] = []
    for page_number, text in pages:
        for part in _split_window(text):
            chunks.append(
                RawChunk(
                    content=part,
                    page_number=page_number,
                    locator=f"p.{page_number}",
                    content_type=BODY,
                )
            )
    return chunks or [RawChunk(content="[no text]", page_number=1, locator="p.1")]


def chunk_segments(segments: list[tuple[float, float, str]]) -> list[RawChunk]:
    chunks: list[RawChunk] = []
    for start, end, text in segments:
        for part in _split_window(text, size=700, overlap=80):
            chunks.append(
                RawChunk(
                    content=part,
                    start_time=start,
                    end_time=end,
                    locator=f"{_fmt(start)}–{_fmt(end)}",
                    content_type=BODY,
                )
            )
    return chunks or [RawChunk(content="[no transcript]", start_time=0, end_time=0, locator="0:00–0:00")]


def _fmt(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def outline_chunk(doc: DocumentLayout) -> RawChunk | None:
    """A single up-front chunk holding the whole section tree.

    This is what makes "这本书每章讲了什么？" answerable: instead of hoping five
    cosine-similar fragments happen to reconstruct the book's shape, the model is
    handed the shape itself, with page ranges.
    """
    body = outline_text(doc)
    if not body:
        return None
    header = "全书目录大纲（层级 / 标题 / 页码）"
    if doc.page_offset is not None and doc.printed_range:
        header += f"；书内页码 = PDF 页码 {doc.page_offset:+d}"
    return RawChunk(
        content=f"{header}\n{body}",
        page_number=1,
        printed_page=None,
        locator="全书大纲",
        content_type=OUTLINE,
    )


def chunk_document(doc: DocumentLayout) -> list[RawChunk]:
    """Turn typed blocks into chunks, preserving type, section and page.

    Ordering rule that keeps retrieval honest: a figure/table/formula chunk opens
    with its caption, so a semantic match on the caption's words lands on the
    object it describes instead of on a bare wall of cell text.
    """
    chunks: list[RawChunk] = []

    front = outline_chunk(doc)
    if front is not None:
        chunks.append(front)

    last_caption = ""
    last_caption_page = -1
    for block in doc.blocks:
        if block.content_type == CAPTION:
            last_caption = block.content.strip() or last_caption
            last_caption_page = block.page_number
        if block.content_type not in RETRIEVABLE_TYPES:
            continue
        content = block.content.strip()
        if not content:
            continue

        if block.content_type in ATOMIC_TYPES:
            # Headings, captions, formulas and table/figure grids are single
            # units: splitting them would separate a label from its object.
            pieces = [content]
        else:
            pieces = _split_paragraphs(content, 900, 120)

        # Fall back to the nearest caption above when the parser could not
        # associate one: a figure is meaningless without its label. The fallback
        # must not cross a page boundary -- a caption left over from the previous
        # page belongs to a different figure, and prefixing it mislabels this one.
        caption = block.parent_caption or (
            last_caption
            if block.content_type in ("table", "figure", "formula")
            and last_caption_page == block.page_number
            else ""
        )

        for piece in pieces:
            body = piece
            if caption and block.content_type in ("table", "figure", "formula"):
                body = f"{caption}\n{piece}"
            if block.section_path:
                body = f"【{block.section_path}】\n{body}"
            chunks.append(
                RawChunk(
                    content=body,
                    page_number=block.page_number,
                    printed_page=block.printed_page,
                    section_title=block.section_path,
                    content_type=block.content_type,
                    locator=_locator(
                        block.page_number, block.printed_page, block.section_path, block.content_type
                    ),
                    heading_level=block.heading_level,
                )
            )
    return chunks or [RawChunk(content="[no text]", page_number=1, locator="p.1")]


def format_excerpts(chunks: list, *, max_chars: int = 6000) -> str:
    """Build a prompt body with chunk ids *and structure* for traceability.

    The header now carries the section and the content type. Without them the
    summariser sees a flat bag of text and produces the scattered outline the
    learner complained about; with them it can say which chapter a point belongs
    to and can treat a formula as a formula.
    """
    parts: list[str] = []
    used = 0
    for chunk in chunks:
        content_type = getattr(chunk, "content_type", BODY) or BODY
        section = getattr(chunk, "section_title", "") or ""
        header = f"[chunk_id={chunk.id} locator={chunk.locator or ''} type={content_type}]"
        if section:
            header += f"\n[section={section}]"
        body = f"{header}\n{chunk.content}"
        if used + len(body) > max_chars and parts:
            break
        parts.append(body)
        used += len(body)
    return "\n\n".join(parts)


def _excerpt_block(chunk) -> str:
    content_type = getattr(chunk, "content_type", BODY) or BODY
    section = getattr(chunk, "section_title", "") or ""
    printed = getattr(chunk, "printed_page", None)
    page = getattr(chunk, "page_number", None)
    header = f"[chunk_id={chunk.id} locator={chunk.locator or ''} type={content_type}"
    if printed is not None:
        header += f" printed_page={printed}"
    if page is not None and page != printed:
        header += f" pdf_page={page}"
    header += "]"
    if section:
        header += f"\n[section={section}]"
    return f"{header}\n{chunk.content}"


def format_document_excerpts(chunks: list, *, max_chars: int = 10000) -> str:
    """Sample a whole document by structure, not by position.

    The previous behaviour took the first ``max_chars`` of the chunk list. On a
    649-page book that is the cover, the CIP page and the preface -- which is why
    the generated summary described nothing and the outline was five unrelated
    topics. Here the budget goes, in order, to:

    1. the document's own table of contents (type ``outline``),
    2. every heading, which *is* the section structure,
    3. an even stride through the rest, so chapter 12 is as likely to be
       represented as chapter 1.
    """
    if not chunks:
        return ""

    def kind(chunk) -> str:
        return getattr(chunk, "content_type", BODY) or BODY

    parts: list[str] = []
    used = 0

    def add(chunk) -> bool:
        nonlocal used
        block = _excerpt_block(chunk)
        if used + len(block) > max_chars:
            return False
        parts.append(block)
        used += len(block)
        return True

    outline = [c for c in chunks if kind(c) == OUTLINE]
    headings = [c for c in chunks if kind(c) == HEADING]
    rest = [c for c in chunks if kind(c) not in (OUTLINE, HEADING)]

    for chunk in outline:
        add(chunk)

    # Headings are short and carry the structure; cap them so a 200-section book
    # cannot crowd out the prose that explains the sections.
    heading_budget = int(max_chars * 0.45)
    heading_used = 0
    for chunk in headings:
        block = _excerpt_block(chunk)
        if heading_used + len(block) > heading_budget:
            break
        if not add(chunk):
            break
        heading_used += len(block)

    if rest and used < max_chars:
        remaining = max_chars - used
        # Stride sampling keeps coverage even when one chapter is 20x another.
        stride = max(1, len(rest) // max(1, remaining // 500))
        picked = rest[::stride]
        for chunk in picked:
            if not add(chunk):
                break
    return "\n\n".join(parts)


__all__ = [
    "CAPTION",
    "HEADING",
    "OUTLINE",
    "TYPE_LABELS",
    "RawChunk",
    "chunk_document",
    "chunk_pages",
    "chunk_segments",
    "format_document_excerpts",
    "format_excerpts",
    "outline_chunk",
]
