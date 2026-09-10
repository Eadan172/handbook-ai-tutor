"""Structural retrieval: the question's page/chapter must pick the chunk.

The bug these cover: "第569页的内容是什么？" retrieved pages 269 and 149, and
"第三章的主题是什么？" retrieved fragments with no chapter label at all, because
the question's numbers were treated as bag-of-words weight rather than as an
address.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.services.rag.base import RetrievalFilter, score_with_filters
from app.services.rag.intent import parse_intent
from app.services.rag.pgvector import rank


def chunk(**kwargs):
    base = {
        "id": uuid4(),
        "source_id": uuid4(),
        "content": "片段内容",
        "locator": None,
        "start_time": None,
        "end_time": None,
        "printed_page": None,
        "page_number": None,
        "section_title": None,
        "content_type": "body",
        "heading_level": None,
        "embedding": [1.0, 0.0],
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


# --------------------------------------------------------------- intent parse


def test_page_reference_is_parsed_from_every_common_phrasing():
    for text in ("第569页的内容是什么？", "见 p.569", "看 page 569", "569 页讲了什么"):
        intent = parse_intent(text)
        assert intent.filter.pages == (569,), text


def test_page_reference_is_validated_against_the_document_range():
    hint = (2, 620)
    assert parse_intent("第569页讲了什么", page_hint=hint).filter.pages == (569,)
    # A year must not be read as a page number.
    assert parse_intent("2022年的版本有什么变化", page_hint=hint).filter.pages == ()
    assert parse_intent("第9999页", page_hint=hint).filter.pages == ()


def test_chapter_reference_is_parsed_including_chinese_numerals():
    assert "第3章" in parse_intent("第三章的主题是什么？").filter.section_terms
    assert "第12章" in parse_intent("第12章讲了什么").filter.section_terms
    assert "第4章" in parse_intent("Chapter 4 的要点").filter.section_terms
    assert "4.4" in parse_intent("4.4 节讲了什么").filter.section_terms


def test_outline_questions_are_detected():
    for text in ("这本书每章讲了什么？", "全书结构是什么", "给我一份目录大纲", "各章主题分别是什么"):
        assert parse_intent(text).wants_outline is True, text
    assert parse_intent("什么是分支预测").wants_outline is False


def test_outline_intent_boosts_outline_and_heading_excerpts():
    intent = parse_intent("这本书每章讲了什么？")
    assert "outline" in intent.filter.prefer_types
    assert "heading" in intent.filter.prefer_types


def test_figure_noise_is_downweighted_for_generic_questions():
    intent = parse_intent("什么是共享存储器")
    assert "figure" in intent.filter.avoid_types
    assert intent.filter.prefer_types == ()

    # ...but a figure question flips that around.
    figure_intent = parse_intent("图 4-12 展示了什么")
    assert "figure" in figure_intent.filter.prefer_types
    assert "figure" not in figure_intent.filter.avoid_types


def test_explicit_type_requests_are_honoured():
    assert "formula" in parse_intent("这一页的公式是什么").filter.prefer_types
    assert "table" in parse_intent("表格里的内容说明了什么").filter.prefer_types


def test_the_word_tushu_does_not_look_like_a_figure_request():
    # "图书" / "试图" must not be mistaken for 图 (figure).
    assert parse_intent("这本书图书结构如何").filter.prefer_types == ()
    assert parse_intent("他试图解释什么").filter.prefer_types == ()


# ----------------------------------------------------------------- re-ranking


def test_a_named_page_beats_a_semantically_closer_chunk():
    target = chunk(printed_page=569, page_number=596, section_title="第4章 > 4.4")
    other = chunk(printed_page=242, page_number=269, section_title="第4章 > 4.4")
    filters = RetrievalFilter(pages=(569,))
    # The wrong page has the higher cosine and still loses.
    assert score_with_filters(target, 0.62, filters) > score_with_filters(other, 0.95, filters)


def test_printed_and_physical_pages_are_both_accepted():
    filters = RetrievalFilter(pages=(569,))
    by_printed = chunk(printed_page=569, page_number=596)
    by_physical = chunk(printed_page=100, page_number=569)
    plain = chunk(printed_page=1, page_number=1)
    assert score_with_filters(by_printed, 0.5, filters) > score_with_filters(plain, 0.9, filters)
    assert score_with_filters(by_physical, 0.5, filters) > score_with_filters(plain, 0.9, filters)


def test_a_named_chapter_boosts_chunks_that_carry_its_section():
    filters = RetrievalFilter(section_terms=("第3章",))
    inside = chunk(section_title="第3章 指令级并行及其利用 > 3.2 分支预测")
    outside = chunk(section_title="第4章 向量、SIMD和 GPU体系结构 > 4.4 图形处理器")
    assert score_with_filters(inside, 0.5, filters) > score_with_filters(outside, 0.9, filters)


def test_headers_and_footers_are_never_retrieved():
    chunks = [
        chunk(embedding=[1.0, 0.0], content_type="header", printed_page=569),
        chunk(embedding=[1.0, 0.0], content_type="footer"),
        chunk(embedding=[0.2, 0.9], content_type="body", printed_page=569),
    ]
    hits = rank(chunks, [1.0, 0.0], top_k=5, filters=None)
    assert [h.content_type for h in hits] == ["body"]


def test_exact_page_hits_are_promoted_even_at_low_similarity():
    chunks = [
        chunk(embedding=[1.0, 0.0], printed_page=242, page_number=269, content_type="body"),
        chunk(embedding=[0.01, 1.0], printed_page=569, page_number=596, content_type="body"),
    ]
    hits = rank(chunks, [1.0, 0.0], top_k=5, filters=RetrievalFilter(pages=(569,)))
    assert hits[0].printed_page == 569


def test_printed_folio_outranks_a_pdf_page_number_of_the_same_value():
    # A 649-page book with 27 front-matter pages gives "569" two readings: the
    # folio printed on the paper (physical 596) and the PDF counter (printed
    # 542). Both are valid and both must survive, but the printed folio leads,
    # because that is the number the book's own running heads use.
    physical = chunk(embedding=[1.0, 0.0], printed_page=542, page_number=569, content_type="body")
    printed = chunk(embedding=[0.5, 0.0], printed_page=569, page_number=596, content_type="body")
    hits = rank([physical, printed], [1.0, 0.0], top_k=5, filters=RetrievalFilter(pages=(569,)))
    assert hits[0].printed_page == 569
    assert len(hits) == 2, "the other reading of 569 must not be dropped"


def test_a_pdf_page_number_alone_still_wins_over_unrelated_pages():
    # Typing a page the book never prints (front matter has no folio) must still
    # address the PDF page rather than return an empty or unrelated answer.
    hits = rank(
        [
            chunk(embedding=[1.0, 0.0], printed_page=None, page_number=5, content_type="body"),
            chunk(embedding=[0.4, 0.0], printed_page=300, page_number=327, content_type="body"),
        ],
        [1.0, 0.0],
        top_k=5,
        filters=RetrievalFilter(pages=(5,)),
    )
    assert hits[0].page_number == 5


def test_a_page_that_matches_nothing_still_returns_the_best_prose():
    # Refusing to answer is worse than answering from the nearest content.
    chunks = [chunk(embedding=[1.0, 0.0], printed_page=10, page_number=10)]
    hits = rank(chunks, [1.0, 0.0], top_k=5, filters=RetrievalFilter(pages=(999,)))
    assert len(hits) == 1


def test_outline_and_heading_chunks_get_a_structural_bonus():
    chunks = [
        chunk(embedding=[0.8, 0.6], content_type="body"),
        chunk(embedding=[0.79, 0.61], content_type="outline"),
        chunk(embedding=[0.79, 0.61], content_type="heading"),
    ]
    hits = rank(chunks, [1.0, 0.0], top_k=3, filters=None)
    assert hits[0].content_type == "outline"
    assert hits[1].content_type == "heading"


def test_structural_fields_survive_the_round_trip_into_retrieved_chunks():
    chunks = [
        chunk(
            embedding=[1.0, 0.0],
            printed_page=569,
            page_number=596,
            section_title="第4章 > 4.4",
            content_type="formula",
            heading_level=None,
        )
    ]
    hit = rank(chunks, [1.0, 0.0], top_k=1, filters=None)[0]
    assert (hit.printed_page, hit.page_number) == (569, 596)
    assert hit.content_type == "formula"
    assert hit.section_title == "第4章 > 4.4"
