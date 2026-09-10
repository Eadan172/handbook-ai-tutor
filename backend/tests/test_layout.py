"""Layout analysis: content-type separation, section map, printed page numbers.

These exercise the pure functions with hand-built lines rather than a PDF, so
they pin the *rules* (what makes a line a caption, how a running head resolves to
a section) without depending on any particular book's fonts.
"""

from __future__ import annotations

import json
import re

from app.services.chunking import chunk_document, format_document_excerpts
from app.services.layout import (
    BODY,
    CAPTION,
    FIGURE,
    FORMULA,
    HEADING,
    OUTLINE,
    TABLE,
    Block,
    DocumentLayout,
    Line,
    OutlineNode,
    PageAnalysis,
    _band_furniture,
    _build_blocks_for_page,
    _classify_line,
    _heading_from_line,
    _looks_like_toc,
    _scan_furniture,
    _title_ok,
    finalise,
    normalise_label,
    outline_text,
    drop_trailing_folio,
)

PAGE_H = 700.0


def line(text: str, ty: float, *, height: float = 10.0, segs: list[tuple[float, str]] | None = None) -> Line:
    """Build a Line the way _page_lines would, from (tx, text) pairs."""
    if segs is None:
        segs = [(50.0, text)]
    segments = [(tx, tx + len(t) * height * 0.95, t) for tx, t in segs]
    return Line(
        text=" ".join(t for _tx, t in segs),
        ty=ty,
        segments=segments,
        height=height,
        size=height,
    )


# --------------------------------------------------------------- text surgery


def test_normalise_label_restores_swallowed_spaces():
    # A PDF has no space glyph here, only an x-advance; without the break the
    # running head cannot be split into "number + title".
    assert normalise_label("4.4图形处理器") == "4.4 图形处理器"
    assert normalise_label("第4章量化设计与分析基础") == "第4章 量化设计与分析基础"
    assert normalise_label("SIMD和GPU体系结构") == "SIMD和 GPU体系结构"
    # A decimal that is not a section number must survive untouched.
    assert normalise_label("人民邮电出版社2022.10重印") == "人民邮电出版社2022.10重印"


def test_drop_trailing_folio_only_after_han():
    assert drop_trailing_folio("计算机的分类5") == "计算机的分类"
    assert drop_trailing_folio("第6版") == "第6版"
    assert drop_trailing_folio("TP303") == "TP303"


def test_heading_parser_rejects_prose_that_starts_with_a_chapter_marker():
    # A preface sentence, not a heading.
    assert _heading_from_line("第7章是这一版新增的内容，介绍了领域专用体系结构，并提供了业内") is None
    assert _heading_from_line("1.3%。") is None
    assert _heading_from_line("3.5%,相当于每20年增长一倍。面向浮点计算的性能也遵循相同的趋势") is None

    assert _heading_from_line("第3章 指令级并行及其利用") == (1, "第3章", "指令级并行及其利用")
    assert _heading_from_line("1.2.6 并行度与并行体系结构的分类") == (3, "1.2.6", "并行度与并行体系结构的分类")
    # A colon is normal inside a real title.
    assert _heading_from_line("1.3.1 指令集体系结构：计算机体系结构的近距离审视") == (
        3,
        "1.3.1",
        "指令集体系结构：计算机体系结构的近距离审视",
    )


def test_title_ok_rejects_bare_markers_only_for_appendix():
    assert _title_ok("", level=1) is True
    assert _title_ok("量化设计与分析基础", level=1) is True
    assert _title_ok("是这一版新增的内容，介绍了领域", level=1) is False


# ------------------------------------------------------------------- fur ntrue


def test_running_head_with_folio_is_furniture_not_body():
    head = line("242 第4章 向量、SIMD和 GPU体系结构中的数据级并行", 668.0, segs=[(8.4, "242"), (46.8, "第4章向量、SIMD和GPU体系结构中的数据级并行")])
    is_furniture, label = _band_furniture(head)
    assert is_furniture is True
    assert "第4章" in label


def test_section_running_head_recognised_even_without_separator():
    # "4.4 图形处理器 243" arrives as "4.4图形处理器" + "243".
    head = line("4.4图形处理器 243", 666.0, segs=[(327.4, "4.4图形处理器"), (425.1, "243")])
    is_furniture, label = _band_furniture(head)
    assert is_furniture is True
    assert label == "4.4 图形处理器"


def test_contents_page_title_is_not_absorbed_as_furniture():
    # If "目 录" were treated as a running head it would vanish into the header
    # and the TOC detector would never see it.
    is_furniture, _ = _band_furniture(line("目 录", 669.0))
    assert is_furniture is False


def test_scan_furniture_keeps_body_when_page_is_all_top_band():
    # A title page whose only text sits high up must not be emptied.
    lines = [line("版权声明", 660.0, height=22.0)]
    header, footer, label, furniture = _scan_furniture(lines, page_height=PAGE_H)
    assert furniture == set()
    assert header == ""


# -------------------------------------------------------------- classification


def test_content_types_are_separated_on_one_page():
    lines = [
        line("242 第4章 向量、SIMD和 GPU体系结构中的数据级并行", 668.0, segs=[(8.4, "242"), (46.8, "第4章向量、SIMD和GPU体系结构中的数据级并行")]),
        # A four-column table row: real column gutters.
        line(
            "类型 描述性名称 的旧术语 GPU术语",
            616.0,
            height=8.0,
            segs=[(5.0, "类型"), (39.6, "描述性名称"), (110.9, "的旧术语"), (187.2, "GPU术语")],
        ),
        line("图 4-6 网格与线程块的关系", 560.0, height=8.0),
        # Figure labels: pure symbol soup, no prose at all.
        line("A[ 512 ] = B [ 512 ] * C[ 512 ]", 520.0, height=7.5),
        line("4.4.3 NVIDIA GPU 的存储器层次结构", 470.0, height=13.0),
        line("和向量体系结构一样，GPU只能很好地解决数据级并行问题。", 430.0),
        line("这两种体系结构类型都拥有集中-分散数据传送和掩码寄存器。", 416.0),
    ]
    blocks, header, _footer = _build_blocks_for_page(
        lines,
        page_number=269,
        page_height=PAGE_H,
        char_width=6.6,
        body_height=10.0,
    )
    kinds = [b.content_type for b in blocks]
    assert "242" in header
    assert TABLE in kinds
    assert CAPTION in kinds
    assert FORMULA in kinds
    assert HEADING in kinds
    assert kinds.count(BODY) >= 1

    by_kind = {b.content_type: b for b in blocks}
    assert "图 4-6" in by_kind[CAPTION].content
    # The table starts left of the text block; that must not drag the paragraph
    # margin across and shatter the prose below into one-line paragraphs.
    body = [b for b in blocks if b.content_type == BODY]
    assert len(body) == 1
    assert "数据级并行" in body[0].content and "掩码寄存器" in body[0].content


def test_figure_text_never_merges_into_a_prose_paragraph():
    lines = [
        line("和向量体系结构一样，GPU只能很好地解决数据级并行问题。", 430.0),
        line("AE 0 =B [ 0 ] * C[ 0 ]", 416.0, height=7.5),
        line("这两种体系结构类型都拥有集中-分散数据传送和掩码寄存器。", 400.0),
    ]
    blocks, _h, _f = _build_blocks_for_page(
        lines, page_number=1, page_height=PAGE_H, char_width=6.6, body_height=10.0
    )
    prose = " ".join(b.content for b in blocks if b.content_type == BODY)
    assert "AE 0" not in prose
    assert any(b.content_type == FORMULA for b in blocks)


def test_paragraphs_split_on_indent():
    lines = [
        line("第一段的第一行内容写在这里并且足够长。", 430.0),
        line("第一段的第二行内容继续写下去。", 416.0),
        line("第二段另起一行，所以应该有缩进。", 390.0, segs=[(70.0, "第二段另起一行，所以应该有缩进。")]),
    ]
    blocks, _h, _f = _build_blocks_for_page(
        lines, page_number=1, page_height=PAGE_H, char_width=6.6, body_height=10.0
    )
    body = [b.content for b in blocks if b.content_type == BODY]
    assert len(body) == 2


def test_toc_page_detected_and_retyped_as_outline():
    lines = [
        line("目 录", 660.0, height=20.0),
        line("第1章 量化设计与分析基础...................1", 600.0),
        line("第2章 存储器层次结构设计...................78", 585.0),
        line("第3章 指令级并行及其利用...................150", 570.0),
    ]
    assert _looks_like_toc(lines) is True
    blocks, _h, _f = _build_blocks_for_page(
        lines, page_number=26, page_height=PAGE_H, char_width=6.6, body_height=10.0
    )
    assert [b.content_type for b in blocks] == [OUTLINE]
    assert "第1章" in blocks[0].content


def test_two_column_toc_page_is_detected_from_segments():
    # A two-column TOC comes back as segments, not whole lines: the geometric
    # parser sees "B.3.3第三种优化方法：提高 | C.1.3RISC指令集的简单实现....565".
    # Judging only on line.text missed it and let one entry anchor the outline
    # (observed on page 27 of the architecture textbook).
    lines = [
        line("", 600.0, segs=[(50.0, "B.3.3第三种优化方法：提高"), (300.0, "C.1.3RISC指令集的简单实现....565")]),
        line("", 585.0, segs=[(50.0, "B.3.4降低流水线分支代价"), (300.0, "C.2流水线冒险...........570")]),
        line("", 570.0, segs=[(50.0, "C.1引言...........564"), (300.0, "C.8谬论与易犯错误..........616")]),
    ]
    assert _looks_like_toc(lines) is True
    blocks, _h, _f = _build_blocks_for_page(
        lines, page_number=27, page_height=PAGE_H, char_width=6.6, body_height=10.0
    )
    assert [b.content_type for b in blocks] == [OUTLINE]


def test_toc_entry_with_dot_leaders_is_never_a_heading():
    # The leaders plus a trailing number are a TOC's fingerprint; a heading
    # carrying them would inject a printed page number into the outline.
    assert _title_ok("流水线：基础与中级概念.......563", level=1) is False
    assert _heading_from_line("附录C流水线：基础与中级概念.......563") is None
    # Without the leaders the same line is a perfectly good heading.
    assert _heading_from_line("附录C 流水线：基础与中级概念") == (1, "附录C", "流水线：基础与中级概念")


def test_appendix_section_numbers_parse_like_chapter_sections():
    # "C.7.1RISC指令集" is the appendix spelling of "4.4 图形处理器".
    assert normalise_label("C.1引言") == "C.1 引言"
    assert _heading_from_line("C.1引言") == (2, "C.1", "引言")
    assert _heading_from_line("B.3.3第三种优化方法：提高") == (3, "B.3.3", "第三种优化方法：提高")
    assert _heading_from_line("A.7指令集编码") == (2, "A.7", "指令集编码")
    # ...but an identifier that merely looks dotted must not become a heading.
    assert _heading_from_line("USB3.0接口") is None
    assert _heading_from_line("4.4图形处理器") == (2, "4.4", "图形处理器")


def test_numbered_prose_is_not_a_heading_however_large_the_type():
    # "4.2 节提到了高存储带宽…" is a sentence that opens with a section number.
    # Promoting it makes it both a section anchor and the section_path of every
    # chunk after it, which is how prose ended up in the outline.
    prose = line("4.2 节提到了高存储带宽对于向量体系结构支持单位步幅、非单位步幅的访问", 400.0, height=18.0)
    assert _classify_line(prose, body_height=10.0, char_width=6.6) == BODY
    wrapped = line("2.3.1 第一种优化：采用小而简单的第一级缓存，缩短命中时间", 385.0, height=18.0)
    assert _classify_line(wrapped, body_height=10.0, char_width=6.6) == BODY
    # A real heading of the same shape is still a heading.
    real = line("4.2 分支预测", 370.0, height=18.0)
    assert _classify_line(real, body_height=10.0, char_width=6.6) == HEADING


def test_colophon_identifiers_are_not_formulas():
    # Symbol density alone typed the copyright page as a wall of formulas:
    # "ISBN978-7-115-56569-3" is hyphen-dense but has no operator.
    assert _classify_line(line("ISBN978-7-115-56569-3", 400.0), body_height=10.0, char_width=6.6) != FORMULA
    assert _classify_line(
        line("网址https://www.ptpress.com.cn", 385.0), body_height=10.0, char_width=6.6
    ) != FORMULA
    # A real formula on the same page still is one.
    assert (
        _classify_line(line("CPI = (Cycles / Instruction)", 370.0), body_height=10.0, char_width=6.6)
        == FORMULA
    )


# ------------------------------------------------ labels, sections, outline


def _page(number: int, header: str, blocks: list[Block] | None = None) -> PageAnalysis:
    page = PageAnalysis(page_number=number, width=500.0, height=PAGE_H, header=header)
    page.blocks = blocks or [
        Block(content="正文内容。", content_type=BODY, page_number=number, page_end=number)
    ]
    return page


def test_printed_page_offset_is_recovered_from_running_heads():
    # Physical 269 carries printed folio 242, i.e. the PDF has 27 pages of
    # front matter ahead of printed page 1.
    pages = [_page(n, f"{n - 27} 第4章 向量、SIMD和 GPU体系结构") for n in range(100, 120)]
    doc = finalise(pages)
    assert doc.page_offset == -27
    assert pages[0].printed_page == 73
    assert doc.printed_range == (73, 92)
    # Front matter must not be back-filled into negative page numbers.
    front = finalise(
        [_page(1, "封面与版权页"), *[_page(n, f"{n - 27} 第1章 量化设计") for n in range(28, 40)]]
    )
    assert front.pages[0].printed_page is None
    assert front.pages[1].printed_page == 1


def test_section_path_is_carried_to_every_block_on_the_page():
    pages = [
        _page(120, "第4章 向量、SIMD和 GPU体系结构中的数据级并行"),
        _page(121, "4.4 图形处理器"),
    ]
    # A heading inside the second page refines the path from that point on.
    pages[1].blocks = [
        Block(content="正文一。", content_type=BODY, page_number=121, page_end=121),
        Block(
            content="4.4.2 NVIDIA GPU 计算结构",
            content_type=HEADING,
            page_number=121,
            page_end=121,
            heading_level=3,
            heading_number="4.4.2",
            heading_title="NVIDIA GPU 计算结构",
        ),
        Block(content="正文二。", content_type=BODY, page_number=121, page_end=121),
    ]
    doc = finalise(pages)
    first, _heading, last = pages[1].blocks
    assert first.section_path == "第4章 向量、SIMD和 GPU体系结构中的数据级并行 > 4.4 图形处理器"
    assert last.section_path.endswith("4.4.2 NVIDIA GPU 计算结构")
    assert doc.pages[1].running_label == "4.4 图形处理器"


def test_section_carries_forward_when_a_page_shows_only_the_chapter():
    # Books alternate: the chapter banner on one side, the section on the other.
    pages = [_page(100, "第3章 指令级并行及其利用"), _page(101, "3.2 分支预测"), _page(102, "第3章 指令级并行及其利用")]
    finalise(pages)
    assert finalise(pages).pages[2].running_label.startswith("第3章")
    assert pages[2].blocks[0].section_path.endswith("3.2 分支预测")


def test_outline_records_page_ranges_and_printed_pages():
    pages = [
        _page(7, "第1章 量化设计与分析基础"),
        _page(8, "1.1 引言"),
        _page(60, "第2章 存储器层次结构设计"),
    ]
    doc = finalise(pages)
    labels = [f"{n.level}:{n.number}" for n in doc.outline]
    assert "1:第1章" in labels
    assert "2:1.1" in labels
    chapter_two = next(n for n in doc.outline if n.number == "第2章")
    assert chapter_two.page_number == 60
    chapter_one = next(n for n in doc.outline if n.number == "第1章")
    assert chapter_one.page_end == 59

    text = outline_text(doc)
    assert "第1章 量化设计与分析基础" in text
    assert "1.1 引言" in text


# ------------------------------------------------------------------- chunking


def test_a_caption_never_crosses_a_page_to_label_another_object():
    # The fallback used to carry the last caption forward for the rest of the
    # book, so a formula on page 569 got labelled with a figure from an earlier
    # page -- a wrong attribution, which is worse than no caption at all.
    doc = DocumentLayout(page_offset=-27, total_pages=600)

    earlier = PageAnalysis(page_number=550, printed_page=523)
    earlier.blocks = [
        Block(
            content="图7-38 一款定制ASIC的5000万美元成本的分解",
            content_type=CAPTION,
            page_number=550,
            printed_page=523,
        )
    ]

    later = PageAnalysis(page_number=596, printed_page=569)
    later.blocks = [
        Block(content="ID/EX、EX/MEM和MEM/WB。", content_type=FORMULA, page_number=596, printed_page=569),
        Block(
            content="图 4-12 共享存储器与全局存储器的关系",
            content_type=CAPTION,
            page_number=596,
            printed_page=569,
        ),
        Block(content="共享存储器 全局存储器", content_type=TABLE, page_number=596, printed_page=569),
    ]

    doc.pages = [earlier, later]
    chunks = chunk_document(doc)

    formula = next(c for c in chunks if c.content_type == FORMULA)
    assert "图7-38" not in formula.content
    # A same-page caption above still applies -- that is the useful case.
    table = next(c for c in chunks if c.content_type == TABLE)
    assert "图 4-12" in table.content


def test_chunks_carry_type_section_and_both_page_numbers():
    doc = DocumentLayout(page_offset=-27, total_pages=600)
    page = PageAnalysis(page_number=596, printed_page=569)
    page.blocks = [
        Block(
            content="4.4.3 NVIDIA GPU 的存储器层次结构",
            content_type=HEADING,
            page_number=596,
            page_end=596,
            printed_page=569,
            section_path="第4章 向量、SIMD和 GPU体系结构中的数据级并行 > 4.4 图形处理器",
            heading_level=3,
            heading_number="4.4.3",
            heading_title="NVIDIA GPU 的存储器层次结构",
        ),
        Block(
            content="GPU 使用共享存储器作为程序员管理的便笺式存储器。",
            content_type=BODY,
            page_number=596,
            page_end=596,
            printed_page=569,
            section_path="第4章 向量、SIMD和 GPU体系结构中的数据级并行 > 4.4 图形处理器",
        ),
        Block(
            content="图 4-12 共享存储器与全局存储器的关系",
            content_type=CAPTION,
            page_number=596,
            page_end=596,
            printed_page=569,
            section_path="第4章 向量、SIMD和 GPU体系结构中的数据级并行 > 4.4 图形处理器",
        ),
        Block(
            content="共享存储器 全局存储器",
            content_type=FIGURE,
            page_number=596,
            page_end=596,
            printed_page=569,
            section_path="第4章 向量、SIMD和 GPU体系结构中的数据级并行 > 4.4 图形处理器",
        ),
    ]
    doc.pages = [page]
    doc.char_count = sum(len(b.content) for b in page.blocks)
    doc.tallies = {BODY: 1, HEADING: 1, CAPTION: 1, FIGURE: 1}
    # Build the outline the way ingest does, so the derived outline chunk exists.
    doc.outline = [
        OutlineNode(level=3, number="4.4.3", title="NVIDIA GPU 的存储器层次结构", page_number=596, printed_page=569)
    ]

    chunks = chunk_document(doc)
    # The document outline is the first chunk, so "这本书讲了什么" has one home.
    assert chunks[0].content_type == OUTLINE
    assert "全书目录大纲" in chunks[0].content
    assert "4.4.3 NVIDIA GPU 的存储器层次结构" in chunks[0].content

    body = next(c for c in chunks if c.content_type == BODY)
    assert body.printed_page == 569
    assert body.page_number == 596
    assert body.section_title.startswith("第4章 向量")
    assert "书内 p.569" in body.locator
    assert "PDF p.596" in body.locator
    # The section is embedded in the text too, so a chapter question matches.
    assert body.content.startswith("【第4章 向量")

    fig = next(c for c in chunks if c.content_type == FIGURE)
    # A figure opens with its caption: a match on the caption's words must land
    # on the figure, not on bare label soup.
    assert fig.content.strip().startswith("【第4章") or "图 4-12" in fig.content
    assert "图 4-12" in fig.content


def test_document_excerpts_sample_the_whole_book_not_just_the_front():
    class C:
        def __init__(self, i: int, kind: str, section: str, text: str) -> None:
            self.id = f"c{i}"
            self.locator = f"p.{i}"
            self.content = text
            self.content_type = kind
            self.section_title = section
            self.page_number = i
            self.printed_page = i

    chunks = [C(0, OUTLINE, "", "全书目录大纲\n第1章 …\n第20章 …")]
    chunks += [
        C(i, HEADING if i % 5 == 0 else BODY, f"第{i // 5 + 1}章", f"内容片段 {i} " * 30)
        for i in range(1, 200)
    ]
    out = format_document_excerpts(chunks, max_chars=4000)
    assert "全书目录大纲" in out
    assert "type=outline" in out

    # Coverage must be spread over the whole document, not stop in the front
    # matter: the old implementation took the first N chunks and never reached
    # chapter 12 of a 600-page book.
    sampled = [int(m) for m in re.findall(r"chunk_id=c(\d+)", out)]
    assert len(sampled) >= 5
    assert max(sampled) >= 150
    assert min(sampled) <= 20


# ------------------------------------------------------------------ json/blob


def test_outline_round_trips_through_the_source_column():
    pages = [_page(7, "第1章 量化设计与分析基础"), _page(8, "1.1 引言")]
    doc = finalise(pages)
    payload = json.dumps(
        [
            {
                "level": n.level,
                "number": n.number,
                "title": n.title,
                "page_number": n.page_number,
                "printed_page": n.printed_page,
                "page_end": n.page_end,
            }
            for n in doc.outline
        ],
        ensure_ascii=False,
    )
    restored = json.loads(payload)
    assert restored[0]["number"] == "第1章"
    assert restored[0]["title"] == "量化设计与分析基础"
