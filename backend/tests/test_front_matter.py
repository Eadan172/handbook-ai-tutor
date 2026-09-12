from __future__ import annotations

from types import SimpleNamespace

from app.services.front_matter import (
    exclude_front_matter,
    is_front_matter_section,
    major_study_sections,
)
from app.services.quiz import _fallback_explanation, major_sections


def test_front_matter_labels_are_skipped():
    for title in (
        "前言",
        "序言",
        "致谢",
        "Preface",
        "Acknowledgements",
        "Acknowledgments",
        "目录",
        "版权信息",
    ):
        assert is_front_matter_section(title), title


def test_numbered_chapter_is_kept_even_if_titled_preface():
    assert not is_front_matter_section("第1章 前言")
    assert not is_front_matter_section("第一章 指令系统")
    assert not is_front_matter_section("Chapter 1 Introduction")


def test_major_sections_start_at_chapter_one():
    chunks = [
        SimpleNamespace(section_title="前言", content_type="body"),
        SimpleNamespace(section_title="致谢", content_type="body"),
        SimpleNamespace(section_title="第1章 指令系统", content_type="body"),
        SimpleNamespace(section_title="第2章 流水线", content_type="body"),
        SimpleNamespace(section_title="", content_type="outline"),
    ]
    assert major_study_sections(chunks) == ["第1章 指令系统", "第2章 流水线"]
    assert major_sections(chunks) == ["第1章 指令系统", "第2章 流水线"]


def test_exclude_front_matter_keeps_outline():
    chunks = [
        SimpleNamespace(section_title="", content_type="outline", content="全书目录"),
        SimpleNamespace(section_title="前言", content_type="body", content="感谢读者"),
        SimpleNamespace(section_title="第1章 体系结构", content_type="body", content="CPU"),
    ]
    kept = exclude_front_matter(chunks)
    assert [c.content for c in kept] == ["全书目录", "CPU"]


def test_empty_answer_fallback_is_chinese_and_names_option():
    q = SimpleNamespace(
        question="序言提到第3章讨论哪种并行？",
        options_json='["数据级并行", "指令级并行（ILP）", "线程级并行", "请求级并行"]',
        correct_index=1,
        question_type="choice",
        reference_answer="",
    )
    text = _fallback_explanation(q, False, "", locator="书内第 3 页")
    assert "未作答" in text
    assert "B." in text
    assert "指令级并行" in text
    assert "第 3 页" in text
    assert "option 0" not in text.lower()
    assert "learner's answer" not in text.lower()
