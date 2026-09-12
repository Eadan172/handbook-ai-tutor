"""Skip book front matter when sampling for quiz / notes / knowledge.

Quiz items and knowledge points should start at 第一章 / Chapter 1, not at
致谢、前言、preface, or acknowledgements. Numbered chapters keep their title
even if it happens to contain those words (e.g. a real 「第1章 前言」).
"""
from __future__ import annotations

import re
from collections import OrderedDict

# Standalone labels. Compared after stripping spaces / punctuation.
_FRONT_MATTER_LABELS = {
    "前言",
    "序言",
    "序",
    "绪论",
    "再版前言",
    "译者序",
    "译者前言",
    "作者序",
    "出版说明",
    "编写说明",
    "致谢",
    "鸣谢",
    "献词",
    "目录",
    "版权",
    "版权信息",
    "内容提要",
    "preface",
    "foreword",
    "prologue",
    "acknowledgements",
    "acknowledgments",
    "acknowledgment",
    "acknowledgement",
    "dedication",
    "contents",
    "table of contents",
    "copyright",
    "front matter",
    "frontmatter",
}

_CHAPTER_RE = re.compile(
    r"^(第\s*[0-9一二三四五六七八九十百千]+\s*[章节篇部]"
    r"|chapter\s+\d+"
    r"|part\s+\d+)",
    re.IGNORECASE,
)

_STRIP_RE = re.compile(r"[\s:：、。·\-—_]+")


def _norm(title: str) -> str:
    return _STRIP_RE.sub("", (title or "").strip()).lower()


def is_front_matter_section(title: str | None) -> bool:
    """True when *title* is front matter rather than a numbered chapter."""
    raw = (title or "").strip()
    if not raw:
        return False
    if _CHAPTER_RE.match(raw):
        return False
    # First path segment of "前言 > 致谢" still counts.
    head = raw.split(">")[0].split("/")[0].strip()
    if _CHAPTER_RE.match(head):
        return False
    return _norm(head) in {_norm(label) for label in _FRONT_MATTER_LABELS} or _norm(raw) in {
        _norm(label) for label in _FRONT_MATTER_LABELS
    }


def exclude_front_matter(chunks: list) -> list:
    """Drop body/heading chunks whose section is front matter.

    Outline chunks stay: the TOC is useful context and is not turned into
    quiz items by itself.
    """
    kept: list = []
    for chunk in chunks:
        kind = getattr(chunk, "content_type", "") or ""
        if kind == "outline":
            kept.append(chunk)
            continue
        title = getattr(chunk, "section_title", None) or ""
        if is_front_matter_section(title):
            continue
        kept.append(chunk)
    return kept


def major_study_sections(chunks: list) -> list[str]:
    """Reading-order section titles, skipping empty / outline / front matter."""
    seen: OrderedDict[str, None] = OrderedDict()
    for chunk in chunks:
        title = (getattr(chunk, "section_title", None) or "").strip()
        kind = getattr(chunk, "content_type", "") or ""
        if not title or kind == "outline":
            continue
        if is_front_matter_section(title):
            continue
        seen[title] = None
    return list(seen)
