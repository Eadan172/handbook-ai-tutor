from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RawChunk:
    content: str
    page_number: int | None = None
    start_time: float | None = None
    end_time: float | None = None
    locator: str | None = None


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


def chunk_pages(pages: list[tuple[int, str]]) -> list[RawChunk]:
    chunks: list[RawChunk] = []
    for page_number, text in pages:
        for part in _split_window(text):
            chunks.append(
                RawChunk(
                    content=part,
                    page_number=page_number,
                    locator=f"p.{page_number}",
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
                )
            )
    return chunks or [RawChunk(content="[no transcript]", start_time=0, end_time=0, locator="0:00–0:00")]


def _fmt(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def format_excerpts(chunks: list, *, max_chars: int = 6000) -> str:
    """Build a prompt body with chunk ids for traceability. Never dump unbounded transcripts."""
    parts: list[str] = []
    used = 0
    for chunk in chunks:
        header = f"[chunk_id={chunk.id} locator={chunk.locator or ''}]"
        body = f"{header}\n{chunk.content}"
        if used + len(body) > max_chars and parts:
            break
        parts.append(body)
        used += len(body)
    return "\n\n".join(parts)
