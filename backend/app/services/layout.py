"""Layout-aware PDF analysis: typed blocks, reading order, section map.

The previous pipeline fed ``page.extract_text()`` straight into chunking. That
call walks the content stream in paint order, so body prose came out interleaved
with figure labels, table cells, formula fragments and the running head. A
reader saw ``ALUOutput*-NPC + （Imm 《 2）`` where the page actually held a figure
label, and every page's running head (``242 第4章 …``) was glued onto the body.

This module reconstructs the page the way a typesetter sees it:

* every text-show operation keeps its real ``tx``/``ty`` and font height,
* operations are grouped into baselines and split into columns by horizontal
  gaps, so a table stays a grid instead of a run-on sentence,
* each line is classified as ``header`` / ``footer`` / ``heading`` / ``caption``
  / ``formula`` / ``table`` / ``figure`` / ``reference`` / ``body``,
* running heads are parsed for the printed page number and the current section,
  which is how a section map is built for books that print the chapter title
  only on the first page of the chapter,
* body lines are merged back into paragraphs using the indent and the line gap,
  never across a heading, caption, formula or table.

Blocks carry that structure downstream, so a chunk knows which section and which
printed page it came from -- and retrieval can filter on it instead of hoping
cosine similarity notices the number "569" inside a question.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from io import BytesIO
from statistics import median

from pypdf import PdfReader

logger = logging.getLogger("app.layout")

# ---------------------------------------------------------------- content types

BODY = "body"
HEADING = "heading"
CAPTION = "caption"
FORMULA = "formula"
TABLE = "table"
FIGURE = "figure"
REFERENCE = "reference"
HEADER = "header"
FOOTER = "footer"
OUTLINE = "outline"

CONTENT_TYPES = (
    BODY,
    HEADING,
    CAPTION,
    FORMULA,
    TABLE,
    FIGURE,
    REFERENCE,
    HEADER,
    FOOTER,
    OUTLINE,
)

#: Types worth embedding and retrieving. Headers/footers are page furniture; the
#: outline is emitted once per document and is handled separately.
RETRIEVABLE_TYPES = (BODY, HEADING, CAPTION, FORMULA, TABLE, FIGURE, REFERENCE)

#: Types that must never be concatenated into a prose paragraph.
ATOMIC_TYPES = (HEADING, CAPTION, FORMULA, TABLE, FIGURE, HEADER, FOOTER, REFERENCE)

TYPE_LABELS = {
    BODY: "正文",
    HEADING: "标题",
    CAPTION: "图注/表注",
    FORMULA: "公式",
    TABLE: "表格",
    FIGURE: "图内文字",
    REFERENCE: "参考文献",
    HEADER: "页眉",
    FOOTER: "页脚",
    OUTLINE: "目录大纲",
}

# --------------------------------------------------------------------- patterns

_CN_NUM = "0-9０-９一二三四五六七八九十百千零两"
_CHAPTER_HEAD = re.compile(rf"^第\s*([{_CN_NUM}]+)\s*([章讲课篇部卷])[\s\.、:：]*(.*)$")
_CHAPTER_HEAD_EN = re.compile(
    r"^(Chapter|Part|Unit|Lesson)\s+([0-9]+|[IVXLCDM]+)\b[\s\.:：-]*(.*)$", re.I
)
#: ``1.2`` and appendix-style ``C.7.1`` are the same shape. A leading letter only
#: counts when it is *not* followed by a second dot group (``C.1``); otherwise
#: "4.4图形处理器" would be read as ``4.4`` but "C.1引言" as prose.
_NUMBER_HEAD = re.compile(
    r"^("
    r"(?:[A-Z]{1,2}\.)?[0-9]{1,3}(?:\.[0-9]{1,3})+"
    r"|[A-Z]{1,2}\.[0-9]{1,3}"
    r")[\s\.、:：]+(\S.*)$"
)
_APPENDIX_HEAD = re.compile(r"^(附\s*录|Appendix)\s*([A-Z0-9]{0,3})[\s\.、:：]*(.*)$", re.I)
_FRONT_MATTER = re.compile(
    r"^(目\s*录|前\s*言|序\s*言|序|引\s*言|导\s*论|摘\s*要|致\s*谢|后\s*记|"
    r"索\s*引|Contents|Preface|Foreword|Introduction|Acknowledg?ments?|Index)\s*$",
    re.I,
)
_EXERCISE_HEAD = re.compile(
    r"^(本?章?小\s*结|本?章?总\s*结|习\s*题|练\s*习|思\s*考\s*题|练\s*一\s*练|"
    r"Exercises?|Problems?|Summary|Review\s+Questions?)\s*$",
    re.I,
)
_REFERENCE_HEAD = re.compile(r"^(参考文献|引用文献|参考书目|References|Bibliography)\s*$", re.I)

_CAPTION_ZH = re.compile(
    r"^(图|圖|表|圖表|插图|附表|附图)\s*([0-9]{1,4}(?:[-–—.．][0-9]{1,4})*)\s*"
)
_CAPTION_EN = re.compile(
    r"^(Figure|Fig\.?|Table|Tab\.?|Listing|Algorithm|Equation|Eq\.?)\s*"
    r"([0-9]+(?:[-–—.][0-9]+)*)",
    re.I,
)
_PAGE_LABEL_ARABIC = re.compile(r"^[\s\-—–_·.,，]*([0-9]{1,4})[\s\-—–_·.,，]*$")
_PAGE_LABEL_ROMAN = re.compile(r"^[\s\-—–_·.,]*([ivxlcdmIVXLCDM]{1,8})[\s\-—–_·.,]*$")

_MATH_CHARS = set("=+−-±∓×÷≤≥≠≈≡∼∈∉⊂⊆∪∩∑∏∫∮√∞∝∂∇→←↔⇒⇔°′″<>")
_MATH_PUNCT = set("[]{}()（）|/\\^*_,;:%·《》")

_SENTENCE_END = "。！？.!?；;：:”』」》>)）]】"
_TITLE_STOP = "，。；！？,;"

#: A table-of-contents entry: dot leaders running out to a page number. Inside a
#: heading this is never legitimate -- it means the line was lifted off a TOC
#: page, and the number in it is a printed page, not a physical one.
_TOC_TAIL = re.compile(r"[\.·⋯…]{3,}\s*[0-9]{1,4}\b")

#: Symbols that only appear in real mathematics. A hyphen-joined identifier such
#: as "ISBN978-7-115-56569-3" is symbol-dense but contains none of these, and the
#: colophon page used to be typed as a wall of formulas because of it.
_STRONG_MATH = set("=+−±×÷≤≥≠≈≡<>∑∏∫√^*/")
_IDENT_LINE = re.compile(r"^(ISBN|ISSN|DOI|CN\b|网址|http)", re.I)
_URL = re.compile(r"https?://|www\.", re.I)


#: A title never opens with one of these. "4.2 节提到了高存储带宽…" is a sentence
#: that happens to start with a section number; a real heading is a noun phrase.
_TITLE_CONTINUATIONS = ("节", "章", "页", "小节", "的", "了", "是")


def _title_ok(title: str, *, level: int) -> bool:
    """Reject prose that merely starts with a chapter marker.

    A preface reads "第7章是这一版新增的内容，介绍了领域专用体系结构…". The
    leading ``第7章`` makes it look like a chapter heading, but a real heading is
    a noun phrase: short, and free of clause punctuation.
    """
    t = title.strip(" .、:：-—")
    if not t:
        return True  # bare marker such as 序言 / 参考文献
    if len(t) > (46 if level == 1 else 64):
        return False
    if _TOC_TAIL.search(t):
        # Dot leaders plus a trailing number: a TOC entry, not a heading.
        return False
    if t.startswith(_TITLE_CONTINUATIONS):
        return False
    if any(ch in _TITLE_STOP for ch in t):
        return False
    if not _paragraph_marks(t):
        return False
    return any(c.isalpha() or _is_cjk_ideograph(c) for c in t)


def _is_cjk_ideograph(ch: str) -> bool:
    o = ord(ch)
    return 0x3400 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF


def _is_cjk_punct(ch: str) -> bool:
    o = ord(ch)
    return 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF


def _is_cjk(ch: str) -> bool:
    return _is_cjk_ideograph(ch) or _is_cjk_punct(ch)


def _math_ratio(text: str) -> tuple[float, int]:
    """Return (symbol density, operator count) used to spot formula lines."""
    s = text.strip()
    if len(s) < 4:
        return 0.0, 0
    math = sum(1 for c in s if c in _MATH_CHARS or c in _MATH_PUNCT)
    latin = sum(1 for c in s if c.isascii() and c.isalnum())
    ops = sum(1 for c in s if c in "=+−-±×÷≤≥≠<>/*^∑∏∫")
    return (math + latin) / len(s), ops


def _is_formula(text: str) -> bool:
    """Symbol density alone is not enough -- see ``_STRONG_MATH``."""
    ratio, ops = _math_ratio(text)
    if ratio < 0.55 or ops < 1:
        return False
    if not any(c in _STRONG_MATH for c in text):
        return False
    return not (_IDENT_LINE.match(text) or _URL.search(text))


def _squash(text: str) -> str:
    return " ".join(text.split())


def _strip_page_marks(piece: str) -> str:
    return piece.strip(".,，、·-—–_:：;；")


#: A dotted section number glued to its title. The lookahead excludes ``.`` so
#: that "1.2.6" is treated as one number rather than split into "1.2 .6".
_GLUE_SECTION = re.compile(
    r"(?<![\d.A-Z])("
    r"(?:[A-Z]{1,2}\.)?[0-9]{1,3}(?:\.[0-9]{1,3})+"
    r"|[A-Z]{1,2}\.[0-9]{1,3}"
    r")(?=[^\s0-9.])"
)
_GLUE_CHAPTER = re.compile(rf"(第\s*[{_CN_NUM}]+\s*[章讲课篇部卷])(?=[^\s])")
_GLUE_CJK_LATIN = re.compile(r"(?<=[\u3400-\u9fff])(?=[A-Za-z]{2,})")
_TRAILING_FOLIO = re.compile(r"(?<=[\u3400-\u9fff])\s*[0-9]{1,4}$")


def normalise_label(text: str) -> str:
    """Restore the spaces a flattened content stream swallows.

    ``4.4图形处理器`` and ``第4章量化设计`` are what a PDF looks like before the
    typesetter's spacing rule is applied: the source has no space glyph, only an
    x-advance. Re-inserting the break is what makes a running head readable and,
    more importantly, parseable as "number + title".
    """
    out = _squash(text)
    out = _GLUE_CHAPTER.sub(r"\1 ", out)
    out = _GLUE_SECTION.sub(r"\1 ", out)
    out = _GLUE_CJK_LATIN.sub(" ", out)
    return _squash(out)


def drop_trailing_folio(label: str) -> str:
    """Strip a folio that the content stream glued onto the end of a running head.

    ``1.2计算机的分类5`` is a section running head plus its page number on the
    same baseline. The digit is only removed when it follows a Han character, so
    a real title such as ``第6版`` or ``TP303`` is left alone.
    """
    return _TRAILING_FOLIO.sub("", label).strip()


# ------------------------------------------------------------------- data model


@dataclass(slots=True)
class Line:
    """One visual baseline, already split into column segments."""

    text: str
    ty: float
    segments: list[tuple[float, float, str]]  # (tx_left, tx_right, text)
    height: float
    size: float

    @property
    def tx_min(self) -> float:
        return min(s[0] for s in self.segments)

    @property
    def tx_max(self) -> float:
        return max(s[1] for s in self.segments)


@dataclass
class Block:
    """A typed structural unit. Blocks are what become chunks."""

    content: str
    content_type: str
    page_number: int
    page_end: int = 0
    printed_page: int | None = None
    section_path: str = ""
    heading_level: int | None = None
    heading_number: str = ""
    heading_title: str = ""
    #: Caption a figure/table region belongs to, when one could be resolved.
    parent_caption: str = ""

    def __post_init__(self) -> None:
        if not self.page_end:
            self.page_end = self.page_number


@dataclass
class OutlineNode:
    level: int
    number: str
    title: str
    page_number: int
    printed_page: int | None = None
    #: Filled after all nodes are known.
    page_end: int | None = None

    @property
    def label(self) -> str:
        return f"{self.number} {self.title}".strip() if self.number else self.title


@dataclass
class PageAnalysis:
    page_number: int
    width: float = 0.0
    height: float = 0.0
    blocks: list[Block] = field(default_factory=list)
    header: str = ""
    footer: str = ""
    printed_page: int | None = None
    running_label: str = ""
    body_height: float = 0.0
    source: str = "text"  # text | ocr | plain


@dataclass
class DocumentLayout:
    pages: list[PageAnalysis] = field(default_factory=list)
    outline: list[OutlineNode] = field(default_factory=list)
    page_offset: int | None = None
    printed_range: tuple[int, int] | None = None
    #: Printed page number -> physical page number, when detectable.
    printed_to_physical: dict[int, int] = field(default_factory=dict)
    tallies: dict[str, int] = field(default_factory=dict)
    char_count: int = 0
    #: Pages in the file, even when only a prefix was analysed.
    total_pages: int = 0
    #: True when layout analysis was skipped/limited, so callers know the
    #: structure is a prefix of the document rather than the whole thing.
    truncated: bool = False

    @property
    def blocks(self) -> list[Block]:
        out: list[Block] = []
        for page in self.pages:
            out.extend(page.blocks)
        return out

    def has_text(self) -> bool:
        return self.char_count >= 24

    def blocks_of(self, content_type: str) -> list[Block]:
        return [b for b in self.blocks if b.content_type == content_type]


# ------------------------------------------------------------------ extraction


def _page_lines(page) -> tuple[list[Line], float]:
    """Return baselines with real coordinates, plus the dominant char width."""
    try:
        from pypdf._text_extraction._layout_mode import (
            fixed_char_width,
            text_show_operations,
            y_coordinate_groups,
        )
        from pypdf.generic import ContentStream
    except Exception:  # pragma: no cover - pypdf internals moved
        return [], 0.0

    contents = page.get("/Contents")
    if contents is None:
        return [], 0.0
    try:
        stream = ContentStream(contents.get_object(), page.pdf, "bytes")
        fonts = page._layout_mode_fonts()
        ops = text_show_operations(iter(stream.operations), fonts, True, None)
    except Exception as exc:
        logger.debug("layout scan failed on a page (%s)", exc)
        return [], 0.0
    if not ops:
        return [], 0.0

    char_width = fixed_char_width(ops, 1.25) or 5.0
    groups = y_coordinate_groups(ops, None)

    lines: list[Line] = []
    for ty, items in groups.items():
        items = sorted(items, key=lambda b: b["tx"])
        segments: list[list] = []
        for item in items:
            text = item["text"]
            right = item["displaced_tx"]
            if not text.strip():
                if segments:
                    segments[-1][1] = max(segments[-1][1], right)
                continue
            tx = item["tx"]
            height = item["font_height"] or 10.0
            gap_limit = max(char_width * 2.2, height * 1.6)
            if segments and tx - segments[-1][1] > gap_limit:
                segments.append([tx, right, text])
            elif segments:
                segments[-1][1] = max(segments[-1][1], right)
                segments[-1][2] += text
            else:
                segments.append([tx, right, text])

        cleaned = [(s[0], s[1], _squash(s[2])) for s in segments if _squash(s[2])]
        if not cleaned:
            continue
        heights = [i["font_height"] for i in items if i["font_height"]]
        sizes = [i["font_size"] for i in items if i["font_size"]]
        lines.append(
            Line(
                text=" ".join(s[2] for s in cleaned),
                ty=float(ty),
                segments=cleaned,
                height=float(median(heights)) if heights else 10.0,
                size=float(median(sizes)) if sizes else 10.0,
            )
        )
    lines.sort(key=lambda ln: -ln.ty)
    return lines, char_width


def _render_lines(lines: list[Line], *, grid: bool, char_width: float) -> str:
    """Join lines. ``grid=True`` keeps column positions for tables/formulas."""
    if grid and char_width > 0:
        out: list[str] = []
        for line in lines:
            parts: list[str] = []
            cursor = 0
            for left, _right, text in line.segments:
                col = int(left / char_width)
                if col > cursor:
                    parts.append(" " * (col - cursor))
                    cursor = col
                parts.append(text)
                cursor += len(text)
            out.append("".join(parts).rstrip())
        return "\n".join(out).strip("\n")

    rendered: list[str] = []
    for line in lines:
        buf = ""
        prev_right: float | None = None
        prev_char = ""
        for left, right, text in line.segments:
            if prev_right is not None:
                gap = left - prev_right
                if gap > max(line.height * 0.4, 1.6):
                    if prev_char and text and not (_is_cjk(prev_char) and _is_cjk(text[0])):
                        buf += " "
            buf += text
            prev_right = right
            if text:
                prev_char = text[-1]
        if buf:
            rendered.append(buf)
    return "\n".join(rendered)


# ------------------------------------------------------------------ classifying


#: A line that *opens* with a heading marker. Used only to detect numbered prose.
_MARKER_HEAD = re.compile(
    rf"^(?:第\s*[{_CN_NUM}]+\s*[章讲课篇部卷]|附\s*录\s*[A-Z0-9]{{0,3}}"
    r"|(?:[A-Z]{1,2}\.)?[0-9]{1,3}(?:\.[0-9]{1,3})+"
    r"|[A-Z]{1,2}\.[0-9]{1,3})"
)


def _numbered_prose(text: str) -> bool:
    """True when a line starts with a section number but continues as a sentence.

    "4.2 节提到了高存储带宽…" and "2.3.1 第一种优化：…，缩短命中时间" are body
    prose. Type size must not promote them: each would become a section anchor
    *and* leak into every following chunk's ``section_path``.
    """
    s = normalise_label(text)
    marker = _MARKER_HEAD.match(s)
    if not marker:
        return False
    rest = s[marker.end() :].strip(" .、:：-—）)")
    if not rest:
        return False
    return not _title_ok(rest, level=2)


def _heading_from_line(text: str) -> tuple[int, str, str] | None:
    """Return (level, number, title) when the line looks like a section heading."""
    s = normalise_label(text)
    if not s or len(s) > 90:
        return None
    if _CAPTION_ZH.match(s) or _CAPTION_EN.match(s):
        return None

    m = _CHAPTER_HEAD.match(s)
    if m:
        title = m.group(3).strip(" .、:：-")
        if not _title_ok(title, level=1):
            return None
        return 1, f"第{m.group(1)}{m.group(2)}", title

    m = _CHAPTER_HEAD_EN.match(s)
    if m:
        title = m.group(3).strip(" .:-")
        if not _title_ok(title, level=1):
            return None
        return 1, f"{m.group(1).title()} {m.group(2)}", title

    m = _APPENDIX_HEAD.match(s)
    if m:
        suffix, title = m.group(2).strip(), m.group(3).strip(" .、:：-")
        if not suffix and not title:
            return None  # a bare cross-reference to "附录", not the appendix itself
        if not _title_ok(title, level=1):
            return None
        return 1, f"附录{suffix}".strip(), title

    if _FRONT_MATTER.match(s) or _REFERENCE_HEAD.match(s):
        return 1, "", s
    if _EXERCISE_HEAD.match(s):
        return 2, "", s

    m = _NUMBER_HEAD.match(s)
    if m:
        number, title = m.group(1), m.group(2).strip(" .、:：-")
        level = max(2, len(number.split(".")))
        if not title or title[0].isdigit() or not _title_ok(title, level=level):
            return None
        return level, number, title

    return None


def _paragraph_marks(text: str) -> bool:
    """A short line with no sentence-final punctuation reads like a heading."""
    return not text.endswith(tuple(_SENTENCE_END))


def _is_probable_heading(
    text: str,
    height: float,
    body_height: float,
    *,
    isolated: bool,
    allowed: bool,
) -> bool:
    """Large type alone is not a heading: a cover page is full of big text.

    A real heading is set off by vertical whitespace, so the font-size path
    additionally requires the line to be isolated and to live past the front
    matter. Pattern-numbered headings do not need either test.
    """
    if not allowed or not isolated:
        return False
    s = _squash(text)
    if not s or len(s) > 60 or not _paragraph_marks(s):
        return False
    if _CAPTION_ZH.match(s) or _CAPTION_EN.match(s):
        return False
    ratio, ops = _math_ratio(s)
    if ratio > 0.55 and ops:
        return False
    return bool(body_height > 0 and height >= body_height * 1.18)


def _band_furniture(line: Line) -> tuple[bool, str]:
    """Decide whether a line in the top/bottom band is page furniture.

    Furniture arrives merged with the folio ("242 第4章向量、SIMD…" is a single
    baseline with two segments), so the test runs on the segments rather than
    the assembled text. Font height is deliberately not consulted: a page
    dominated by a table makes the running head look oversized, which used to
    let the folio leak into the body and broke printed-page detection.
    """
    text = _squash(line.text)
    if not text:
        return False, ""

    if _PAGE_LABEL_ARABIC.match(text) or _PAGE_LABEL_ROMAN.match(text):
        return True, ""

    kept = [
        seg[2]
        for seg in line.segments
        if not _PAGE_LABEL_ARABIC.match(_strip_page_marks(seg[2]))
        and not _PAGE_LABEL_ROMAN.match(_strip_page_marks(seg[2]))
    ]
    stripped = drop_trailing_folio(normalise_label(" ".join(kept)))
    if not stripped:
        return True, ""

    # "目 录" / "参考文献" sitting at the top of a page are the page's own heading,
    # not a running head -- absorbing them would hide the contents page from the
    # TOC detector and make the front matter look like chapter one.
    if (
        _FRONT_MATTER.match(stripped)
        or _EXERCISE_HEAD.match(stripped)
        or _REFERENCE_HEAD.match(stripped)
    ):
        return False, ""

    head = _heading_from_line(stripped)
    if head is not None and head[1]:
        return True, stripped
    if _RUNNING_NUMBER.match(stripped):
        return True, stripped
    if len(stripped) <= 40 and _paragraph_marks(stripped):
        return True, stripped
    return False, ""


_RUNNING_NUMBER = re.compile(r"^([0-9]{1,2}(?:\.[0-9]{1,3}){1,4})\s*([^\s0-9].*)$")


def _scan_furniture(
    lines: list[Line], *, page_height: float
) -> tuple[str, str, str, set[int]]:
    """Split a page into (header, footer, running label, furniture indices)."""
    if not lines or page_height <= 0:
        return "", "", "", set()

    top_cut = page_height * 0.90
    bottom_cut = page_height * 0.075
    if not any(bottom_cut < ln.ty < top_cut for ln in lines):
        # A title page whose only text sits in the top band would otherwise lose
        # its entire content to the furniture filter.
        return "", "", "", set()

    header_lines: list[Line] = []
    footer_lines: list[Line] = []
    furniture: set[int] = set()
    for index, line in enumerate(lines):
        if line.ty >= top_cut:
            ok, _label = _band_furniture(line)
            if ok:
                header_lines.append(line)
                furniture.add(index)
        elif line.ty <= bottom_cut:
            ok, _label = _band_furniture(line)
            if ok:
                footer_lines.append(line)
                furniture.add(index)

    header = normalise_label(_join_band(header_lines))
    footer = normalise_label(_join_band(footer_lines))
    return header, footer, _running_label(header, footer), furniture


def _join_band(lines: list[Line]) -> str:
    parts: list[str] = []
    for line in lines:
        for _left, _right, text in line.segments:
            parts.append(text)
    return " ".join(parts)


def _classify_line(
    line: Line,
    *,
    body_height: float,
    char_width: float,
    isolated: bool = True,
    size_heading_allowed: bool = True,
) -> str:
    text = _squash(line.text)
    if not text:
        return BODY
    if _CAPTION_ZH.match(text) or _CAPTION_EN.match(text):
        return CAPTION

    if len(line.segments) >= 3:
        return TABLE
    if len(line.segments) == 2 and line.height <= body_height * 0.92:
        # A two-column row: real column gutter, type smaller than the prose.
        gutter = line.segments[1][0] - line.segments[0][1]
        if gutter >= char_width * 3:
            return TABLE

    if _is_formula(text):
        return FORMULA
    if _heading_from_line(normalise_label(text)):
        return HEADING
    if _numbered_prose(text):
        # Opens with a section number but reads as a sentence -- large type or
        # an isolated line must not turn it into a heading.
        return BODY
    if _is_probable_heading(
        text,
        line.height,
        body_height,
        isolated=isolated,
        allowed=size_heading_allowed,
    ):
        return HEADING
    return BODY


_TOC_TITLE = re.compile(r"^(目\s*录|Contents|CONTENTS|目次)$", re.I)


def _looks_like_toc(lines: list[Line]) -> bool:
    """True when the page is a table of contents.

    A TOC is a list of chapter/section lines with dot leaders running out to a
    page number. Its entries must not anchor the outline -- the numbers beside
    them are printed pages, not physical ones -- but the text itself is the most
    honest answer to "what is this book about", so it is kept as content, just
    retyped.

    Book TOCs are frequently set in two columns, in which case the geometric
    parser hands back *segments* rather than whole lines; both levels have to be
    inspected or a two-column TOC page slips through and one of its entries ends
    up anchoring the outline (observed: page 27 of the architecture textbook).
    """
    if any(_TOC_TITLE.match(_squash(ln.text)) for ln in lines):
        return True
    entries = 0
    for line in lines:
        for piece in _toc_pieces(line):
            if not piece or len(piece) > 120:
                continue
            tail = _TOC_TAIL.search(piece)
            if not tail:
                continue
            head = _heading_from_line(piece[: tail.start()])
            if head and head[0] <= 3:
                entries += 1
    return entries >= 3


def _toc_pieces(line: Line) -> list[str]:
    """Candidate TOC-entry strings for one baseline: the line and its columns."""
    pieces = [_squash(line.text)]
    if len(line.segments) > 1:
        pieces.extend(_squash(seg[2]) for seg in line.segments)
    return pieces


# ------------------------------------------------------------------- page build


def _build_blocks_for_page(
    lines: list[Line],
    *,
    page_number: int,
    page_height: float,
    char_width: float,
    body_height: float,
    furniture: set[int] | None = None,
    header: str = "",
    footer: str = "",
    size_heading_allowed: bool = True,
) -> tuple[list[Block], str, str]:
    """Classify lines, split off page furniture, then merge prose paragraphs."""
    if not lines:
        return [], "", ""

    if furniture is None:
        header, footer, _label, furniture = _scan_furniture(lines, page_height=page_height)

    body_lines = [ln for i, ln in enumerate(lines) if i not in furniture]
    if not body_lines:
        return [], header, footer

    # A table of contents keeps its text but is retyped: its entries cannot
    # anchor the outline, because the numbers beside them are printed pages.
    if _looks_like_toc(body_lines):
        merged = normalise_label(_render_lines(body_lines, grid=False, char_width=char_width))
        block = Block(
            content=merged,
            content_type=OUTLINE,
            page_number=page_number,
            page_end=page_number,
        )
        return ([block] if merged.strip() else []), header, footer

    # The paragraph margin is the *modal* left edge, not the minimum: a table or
    # a figure that starts left of the text block would otherwise drag the
    # margin across and make every prose line look indented -- which splits the
    # whole page into one-sentence paragraphs.
    edges: Counter[float] = Counter()
    for ln in body_lines:
        edges[round(ln.tx_min)] += 1
    top = max(edges.values()) if edges else 0
    margin = min(value for value, count in edges.items() if count == top) if edges else 0.0
    indent_limit = max(char_width * 1.6, 6.0)

    kinds: list[str] = []
    for index, line in enumerate(body_lines):
        above = (
            body_lines[index - 1].ty - line.ty - line.height if index > 0 else 999.0
        )
        below = (
            line.ty - body_lines[index + 1].ty - body_lines[index + 1].height
            if index + 1 < len(body_lines)
            else 999.0
        )
        isolated = max(above, below) >= line.height * 0.55
        kinds.append(
            _classify_line(
                line,
                body_height=body_height,
                char_width=char_width,
                isolated=isolated,
                size_heading_allowed=size_heading_allowed,
            )
        )

    blocks: list[Block] = []
    pending: list[Line] = []

    def make_block(content: str, content_type: str, **extra) -> None:
        if content.strip():
            blocks.append(
                Block(
                    content=content,
                    content_type=content_type,
                    page_number=page_number,
                    page_end=page_number,
                    section_path="",
                    **extra,
                )
            )

    def flush() -> None:
        if not pending:
            return
        make_block(_reflow_paragraph(pending, char_width), BODY)
        pending.clear()

    index = 0
    while index < len(body_lines):
        line = body_lines[index]
        kind = kinds[index]

        if kind == BODY:
            if pending:
                prev = pending[-1]
                gap = prev.ty - line.ty
                step = max(prev.height, line.height, 1.0)
                indented = (line.tx_min - margin) >= indent_limit
                if indented or gap > step * 2.2:
                    flush()
                elif prev.text and prev.text[-1] in "。！？”』」》" and gap > step * 1.55:
                    flush()
            pending.append(line)
            index += 1
            continue

        flush()
        run = [line]
        while index + 1 < len(body_lines) and kinds[index + 1] == kind:
            index += 1
            run.append(body_lines[index])

        if kind == HEADING:
            for head_line in run:
                head = _heading_from_line(head_line.text)
                make_block(
                    normalise_label(head_line.text),
                    HEADING,
                    heading_level=head[0] if head else 2,
                    heading_number=head[1] if head else "",
                    heading_title=(head[2] if head else "") or normalise_label(head_line.text),
                )
        else:
            grid = kind in (TABLE, FIGURE, FORMULA)
            make_block(_render_lines(run, grid=grid, char_width=char_width), kind)
        index += 1

    flush()
    return _attach_captions(blocks), header, footer


def _reflow_paragraph(lines: list[Line], char_width: float) -> str:
    """Join wrapped lines into one paragraph, CJK-aware (no space between Han)."""
    out = ""
    for line in lines:
        piece = _render_lines([line], grid=False, char_width=char_width).strip()
        if not piece:
            continue
        if not out:
            out = piece
        elif _is_cjk(out[-1]) or _is_cjk(piece[0]):
            out += piece
        elif out[-1] == "-" and piece[0].islower():
            out = out[:-1] + piece
        else:
            out += " " + piece
    return out


def _attach_captions(blocks: list[Block]) -> list[Block]:
    """Give figure/table runs the nearest caption above (else below) them."""
    for index, block in enumerate(blocks):
        if block.content_type not in (FIGURE, TABLE, FORMULA):
            continue
        for offset in range(1, 4):
            above = index - offset
            if above >= 0 and blocks[above].content_type == CAPTION:
                block.parent_caption = blocks[above].content
                break
            below = index + offset
            if below < len(blocks) and blocks[below].content_type == CAPTION:
                block.parent_caption = blocks[below].content
                break
    return blocks


# ------------------------------------------------------------------ page labels


def _page_label_from_text(*texts: str) -> list[int]:
    """Pull bare folio numbers out of running heads / feet."""
    values: list[int] = []
    for raw in texts:
        if not raw:
            continue
        for piece in raw.split():
            m = _PAGE_LABEL_ARABIC.match(_strip_page_marks(piece))
            if m:
                value = int(m.group(1))
                if 0 < value < 100_000:
                    values.append(value)
    return values


def _detect_page_labels(pages: list[PageAnalysis]) -> tuple[int | None, int | None]:
    """Resolve printed page numbers from the page furniture.

    A stray "1" inside a table would poison a per-page guess, so the offset is
    taken as the *mode* of (printed - physical) across the whole document, and a
    page then keeps only the candidate that agrees with that fit.

    Returns ``(offset, first_numbered_physical_page)``.
    """
    candidates: dict[int, list[int]] = {}
    for page in pages:
        values = _page_label_from_text(page.header, page.footer)
        if values:
            candidates[page.page_number] = values

    if not candidates:
        return None, None

    offsets: Counter[int] = Counter()
    for physical, values in candidates.items():
        for value in values:
            offsets[value - physical] += 1
    offset, hits = offsets.most_common(1)[0]
    if hits < 2 and len(candidates) > 2:
        return None, None

    numbered = sorted(p for p, values in candidates.items() if offset + p in values)
    consistency = len(numbered) / max(1, len(candidates))
    if consistency < 0.35:
        return None, None

    first_numbered = numbered[0] if numbered else 1

    for page in pages:
        values = candidates.get(page.page_number, [])
        if offset + page.page_number in values:
            page.printed_page = offset + page.page_number
        elif page.page_number >= first_numbered and offset + page.page_number >= 1:
            # Front matter (cover, CIP page, TOC) carries no folio; back-filling
            # from the first numbered page onward is what a reader would expect.
            page.printed_page = offset + page.page_number
    return offset, first_numbered


def _running_label(header: str, footer: str) -> str:
    """Strip the folio off a running head, keeping the chapter/section text."""
    for raw in (header, footer):
        if not raw:
            continue
        parts = [
            piece
            for piece in (_strip_page_marks(p) for p in raw.split())
            if piece and not _PAGE_LABEL_ARABIC.match(piece)
        ]
        label = drop_trailing_folio(_squash(" ".join(parts)))
        if len(label) >= 2:
            return label
    return ""


# ------------------------------------------------------------------- finalise


def finalise(analyses: list[PageAnalysis]) -> DocumentLayout:
    """Resolve page labels, section paths, and the document outline."""
    doc = DocumentLayout(pages=analyses)

    # The running label is what carries the chapter/section across pages, so it
    # is always derived from the furniture when a caller assembled pages by hand.
    for page in analyses:
        if not page.running_label and (page.header or page.footer):
            page.running_label = _running_label(page.header, page.footer)

    doc.page_offset, _first = _detect_page_labels(analyses)

    for page in analyses:
        for block in page.blocks:
            block.printed_page = page.printed_page

    _assign_sections(analyses)
    doc.outline = _build_outline(analyses)
    _stitch_outline_pages(
        doc.outline, max_page=analyses[-1].page_number if analyses else 0
    )

    tallies: Counter[str] = Counter()
    for page in analyses:
        for block in page.blocks:
            tallies[block.content_type] += 1
            doc.char_count += len(block.content)
    doc.tallies = dict(tallies)

    pairs = [
        (page.printed_page, page.page_number)
        for page in analyses
        if page.printed_page is not None
    ]
    if pairs:
        doc.printed_to_physical = dict(pairs)
        doc.printed_range = (min(p[0] for p in pairs), max(p[0] for p in pairs))
    return doc


def _is_toc_page(page: PageAnalysis) -> bool:
    return any(block.content_type == OUTLINE for block in page.blocks)


def _assign_sections(analyses: list[PageAnalysis]) -> None:
    """Stamp every block with its chapter/section path.

    The running head is authoritative for a page (it is printed on every page),
    while an explicit in-body heading refines the path from its own position
    onward. Both are needed: a book prints its chapter title only on the first
    page of the chapter, so the chapter would otherwise be unknown for the
    remaining dozens of pages.
    """
    chapter = ""
    section = ""

    for page in analyses:
        parsed = (
            None
            if _is_toc_page(page)
            else _heading_from_line(page.running_label)
            if page.running_label
            else None
        )
        if parsed:
            level, number, title = parsed
            if level == 1:
                chapter = f"{number} {title}".strip() if number else title
            else:
                section = f"{number} {title}".strip() if number else title

        current = " > ".join(p for p in (chapter, section) if p)

        for block in page.blocks:
            if block.content_type == HEADING:
                if block.heading_level == 1:
                    chapter = (
                        f"{block.heading_number} {block.heading_title}".strip()
                        if block.heading_number
                        else block.heading_title
                    )
                    section = ""
                else:
                    section = (
                        f"{block.heading_number} {block.heading_title}".strip()
                        if block.heading_number
                        else block.heading_title
                    )
                current = " > ".join(p for p in (chapter, section) if p)
            block.section_path = current


def _build_outline(analyses: list[PageAnalysis]) -> list[OutlineNode]:
    nodes: list[OutlineNode] = []
    seen: set[tuple[int, str]] = set()

    def add(level: int, number: str, title: str, page: PageAnalysis) -> None:
        token = number or title
        key = (level, token)
        if not token or key in seen:
            return
        seen.add(key)
        nodes.append(
            OutlineNode(
                level=level,
                number=number,
                title=title,
                page_number=page.page_number,
                printed_page=page.printed_page,
            )
        )

    for page in analyses:
        if _is_toc_page(page):
            # The TOC's own text is kept as content (retrievable verbatim); it
            # just must not define page anchors, which would be printed pages.
            continue
        parsed = _heading_from_line(page.running_label) if page.running_label else None
        if parsed:
            add(parsed[0], parsed[1], parsed[2], page)
        for block in page.blocks:
            if block.content_type == HEADING:
                add(
                    block.heading_level or 2,
                    block.heading_number,
                    block.heading_title,
                    page,
                )

    nodes.sort(key=lambda n: (n.page_number, n.level))
    return nodes


def _stitch_outline_pages(nodes: list[OutlineNode], *, max_page: int) -> None:
    """Fill page_end so every entry owns a page range.

    A chapter runs until the next chapter, not until the first subsection inside
    it, so an entry is closed by the next node at the same level or higher.
    Closing a parent on its own child would give "第1章" a one-page range on
    every book whose chapter starts with a section heading.
    """
    ordered = sorted(nodes, key=lambda n: (n.page_number, n.level))
    open_nodes: list[OutlineNode] = []
    for node in ordered:
        while open_nodes:
            top = open_nodes[-1]
            same_or_higher = top.level >= node.level
            if not same_or_higher:
                break
            if (top.page_number, top.level) >= (node.page_number, node.level):
                break
            open_nodes.pop()
            top.page_end = max(top.page_number, node.page_number - 1)
        open_nodes.append(node)

    for node in open_nodes:
        node.page_end = max(node.page_number, max_page)


def outline_text(doc: DocumentLayout, *, max_nodes: int = 400) -> str:
    """Render the outline as a compact, prompt-friendly block."""
    lines: list[str] = []
    for node in doc.outline[:max_nodes]:
        if node.level > 4:
            continue
        span = f"p.{node.page_number}"
        if node.printed_page is not None:
            span = f"书内 p.{node.printed_page} / PDF p.{node.page_number}"
        lines.append(f"{'  ' * (node.level - 1)}- [{node.level}] {node.label}  ({span})")
    return "\n".join(lines)


# ------------------------------------------------------------------- public API


def analyse_pdf(data: bytes, *, max_pages: int | None = None) -> DocumentLayout:
    """Full layout analysis of a PDF that is expected to carry a text layer.

    Three passes, because each answer needs the previous one:

    1. geometry only -- enough to find the document's real body type size,
    2. page furniture -- folios and running heads, which localise the printed
       page numbers and therefore where the front matter ends,
    3. classification -- blocking, typing and section assignment, using the
       front-matter boundary so a cover page's 30pt type is not mistaken for a
       heading and a CIP page's chapter listing is not mistaken for the outline.
    """
    try:
        reader = PdfReader(BytesIO(data), strict=False)
        raw_pages = list(reader.pages)
    except Exception as exc:
        logger.warning("cannot open pdf for layout analysis (%s)", exc)
        return DocumentLayout()
    total_pages = len(raw_pages)
    if max_pages:
        raw_pages = raw_pages[:max_pages]

    staged: list[tuple[PageAnalysis, list[Line], float, float]] = []
    page_heights: list[float] = []
    for index, page in enumerate(raw_pages, start=1):
        try:
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
        except Exception:
            width = height = 0.0
        try:
            lines, char_width = _page_lines(page)
        except Exception as exc:  # one broken page must not kill the document
            logger.warning("page %s: layout analysis failed (%s)", index, exc)
            lines, char_width = [], 0.0

        analysis = PageAnalysis(page_number=index, width=width, height=height)
        local: Counter[float] = Counter()
        for line in lines:
            local[round(line.height, 1)] += max(1, len(line.text))
        if local:
            analysis.body_height = local.most_common(1)[0][0]
            page_heights.append(analysis.body_height)
        staged.append((analysis, lines, char_width, height))

    # The body size is a property of the book, not of a single page: a page that
    # happens to be one big table would otherwise report the table's 8pt as the
    # prose size and call every real sentence in it oversized.
    doc_body_height = median(page_heights) if page_heights else 10.0

    furniture_by_page: dict[int, tuple[str, str, str, set[int]]] = {}
    for analysis, lines, _cw, height in staged:
        if lines:
            furniture_by_page[analysis.page_number] = _scan_furniture(
                lines, page_height=height
            )
            header, footer, label, _idx = furniture_by_page[analysis.page_number]
            analysis.header = header
            analysis.footer = footer
            analysis.running_label = label
        else:
            try:
                fallback = (raw_pages[analysis.page_number - 1].extract_text() or "").strip()
            except Exception:
                fallback = ""
            if fallback:
                analysis.source = "plain"

    offset, first_numbered = _detect_page_labels([a for a, *_ in staged])

    prose_start = 1
    for analysis, lines, _cw, _h in staged:
        if sum(1 for ln in lines if len(_squash(ln.text)) >= 30) >= 6:
            prose_start = analysis.page_number
            break
    # Folios are a better front-matter signal than prose density when present.
    content_start = first_numbered if first_numbered else prose_start

    analyses: list[PageAnalysis] = []
    for analysis, lines, char_width, height in staged:
        if not lines:
            if analysis.source == "plain":
                try:
                    fallback = (
                        raw_pages[analysis.page_number - 1].extract_text() or ""
                    ).strip()
                except Exception:
                    fallback = ""
                if fallback:
                    analysis.blocks = [
                        Block(
                            content=fallback,
                            content_type=BODY,
                            page_number=analysis.page_number,
                            page_end=analysis.page_number,
                        )
                    ]
            analyses.append(analysis)
            continue

        header, footer, _label, furniture = furniture_by_page[analysis.page_number]
        blocks, _h, _f = _build_blocks_for_page(
            lines,
            page_number=analysis.page_number,
            page_height=height,
            char_width=char_width,
            body_height=doc_body_height,
            furniture=furniture,
            header=header,
            footer=footer,
            size_heading_allowed=analysis.page_number >= content_start,
        )
        analysis.blocks = blocks
        analysis.body_height = doc_body_height
        analyses.append(analysis)

    if offset is not None:
        logger.info(
            "printed page offset %+d resolved from %s numbered page(s)",
            offset,
            sum(1 for a in analyses if a.printed_page is not None),
        )
    doc = finalise(analyses)
    doc.total_pages = total_pages
    doc.truncated = total_pages > len(analyses)
    return doc


def _classify_text_line(text: str) -> str:
    if _CAPTION_ZH.match(text) or _CAPTION_EN.match(text):
        return CAPTION
    if _is_formula(text):
        return FORMULA
    if _heading_from_line(text):
        return HEADING
    return BODY


def analyse_text_pages(
    pages: list[tuple[int, str]],
    *,
    source: str = "ocr",
) -> DocumentLayout:
    """Classify a text-only extraction (OCR / vision) that has no coordinates.

    Without geometry the only signals left are the line text and the surrounding
    blank lines, which is still enough to separate captions, formulas, headings
    and running heads from prose. The top two lines are inspected for a folio so
    scanned books stay addressable by printed page.
    """
    analyses: list[PageAnalysis] = []
    for page_number, raw in pages:
        text = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
        raw_lines = text.split("\n")
        stripped = [(i, _squash(ln)) for i, ln in enumerate(raw_lines) if _squash(ln)]

        entry = PageAnalysis(page_number=page_number, source=source)
        kept = list(raw_lines)

        if len(stripped) > 2:
            first_index, first = stripped[0]
            last_index, last = stripped[-1]
            folio_head = bool(re.fullmatch(r"[0-9]{1,4}", first))
            folio_tail = bool(re.fullmatch(r"[0-9]{1,4}", last))
            if folio_head:
                entry.header = first
                kept = raw_lines[first_index + 1 :]
            elif folio_tail:
                entry.footer = last
                kept = raw_lines[:last_index]
            if entry.header and len(stripped) > 1:
                _, second = stripped[1]
                if _heading_from_line(second):
                    entry.header = f"{first} {second}"
                    kept = raw_lines[stripped[1][0] + 1 :]
            entry.running_label = _running_label(entry.header, entry.footer)
            values = _page_label_from_text(entry.header, entry.footer)
            if values:
                entry.printed_page = values[0]

        blocks: list[Block] = []
        pending: list[str] = []
        for raw_line in kept:
            line = _squash(raw_line)
            if not line:
                continue
            kind = _classify_text_line(line)
            if kind == BODY:
                pending.append(line)
                continue
            if pending:
                blocks.append(_paragraph_block("\n".join(pending), page_number))
                pending.clear()
            if kind == HEADING:
                head = _heading_from_line(line)
                blocks.append(
                    Block(
                        content=line,
                        content_type=HEADING,
                        page_number=page_number,
                        page_end=page_number,
                        heading_level=head[0] if head else 2,
                        heading_number=head[1] if head else "",
                        heading_title=(head[2] if head else "") or line,
                    )
                )
            else:
                blocks.append(
                    Block(
                        content=line,
                        content_type=kind,
                        page_number=page_number,
                        page_end=page_number,
                    )
                )
        if pending:
            blocks.append(_paragraph_block("\n".join(pending), page_number))
        entry.blocks = _attach_captions(blocks)
        analyses.append(entry)

    return finalise(analyses)


def _paragraph_block(text: str, page_number: int) -> Block:
    return Block(
        content=text,
        content_type=BODY,
        page_number=page_number,
        page_end=page_number,
    )


__all__ = [
    "ATOMIC_TYPES",
    "BODY",
    "CAPTION",
    "CONTENT_TYPES",
    "DocumentLayout",
    "FIGURE",
    "FOOTER",
    "FORMULA",
    "HEADER",
    "HEADING",
    "Line",
    "OUTLINE",
    "OutlineNode",
    "PageAnalysis",
    "REFERENCE",
    "RETRIEVABLE_TYPES",
    "TABLE",
    "TYPE_LABELS",
    "Block",
    "analyse_pdf",
    "analyse_text_pages",
    "finalise",
    "outline_text",
]
