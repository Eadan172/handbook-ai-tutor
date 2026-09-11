"""A recording must always present a usable, jumpable structure.

Two behaviours are covered here because both were reported from the UI:

  * an mp4 whose `section_outline_json` is empty (rows ingested before the
    chapter pass existed) still has to show chapters — the timestamps are sitting
    right there in `document_chunks`, so the structure is rebuilt from them
    instead of reporting "没有任何结构分析结果";
  * pressing 「LLM 重新生成」 must never retitle a recording. The model's headline
    describes the content and belongs on the summary; the video keeps its file
    name.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.core.db import SessionLocal
from app.models.chunk import DocumentChunk
from app.models.source import Source
from tests.conftest import auth_header

NOW = datetime.now(timezone.utc)


async def _seed_video(
    user_id: UUID,
    *,
    filename: str = "lesson.mp4",
    title: str | None = None,
    outline_json: str | None = None,
    chunks: list[tuple[float, float, str]] | None = None,
) -> UUID:
    """Insert a ready video source and its transcript chunks directly.

    Going through the upload endpoint would drag in ffmpeg and a real STT run;
    what is under test here is the *reading* side, so the rows are written as the
    pipeline would have left them.
    """
    source_id = uuid4()
    async with SessionLocal() as session:
        session.add(
            Source(
                id=source_id,
                user_id=user_id,
                filename=filename,
                content_type="video/mp4",
                kind="video",
                storage_key=f"{user_id}/{source_id}/{filename}",
                byte_size=1024,
                status="ready",
                title=title or filename,
                section_outline_json=outline_json,
            )
        )
        for ordinal, (start, end, section) in enumerate(chunks or []):
            session.add(
                DocumentChunk(
                    source_id=source_id,
                    user_id=user_id,
                    ordinal=ordinal,
                    content=f"转录片段 {ordinal}",
                    start_time=start,
                    end_time=end,
                    locator="0:00–0:30",
                    content_type="body",
                    section_title=section or None,
                    heading_level=1 if section else None,
                )
            )
        await session.commit()
    return source_id


async def _user_id(client: AsyncClient, headers: dict[str, str]) -> UUID:
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return UUID(me.json()["id"])


@pytest.mark.asyncio
async def test_video_without_a_stored_outline_still_reports_chapters(client: AsyncClient) -> None:
    """The real DB holds 976 timestamped chunks and an empty outline column."""
    headers = await auth_header(client, email="vstruct@example.com")
    uid = await _user_id(client, headers)
    source_id = await _seed_video(
        uid,
        outline_json=None,
        chunks=[(i * 30.0, i * 30.0 + 30.0, "") for i in range(40)],
    )

    resp = await client.get(f"/api/v1/sources/{source_id}/structure", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["kind"] == "video"
    assert data["outline"], "a recording with timestamps must never report 'no structure'"
    assert len(data["outline"]) >= 2
    # Every chapter needs a real jump target, and must stay inside the recording.
    for node in data["outline"]:
        assert node["start_time"] is not None
        assert node["end_time"] is not None
        assert node["start_time"] < node["end_time"]
    assert data["duration"] == pytest.approx(1200.0)
    # No page semantics may leak into a recording.
    assert data["page_count"] is None


@pytest.mark.asyncio
async def test_video_chapters_follow_the_chunker_tags_when_present(client: AsyncClient) -> None:
    headers = await auth_header(client, email="vtagged@example.com")
    uid = await _user_id(client, headers)
    chapters = ["字母表概览", "元音字母", "辅音字母", "发音练习"]
    chunks = [
        (i * 30.0, i * 30.0 + 30.0, chapters[i // 10]) for i in range(40)
    ]
    source_id = await _seed_video(uid, chunks=chunks)

    data = (
        await client.get(f"/api/v1/sources/{source_id}/structure", headers=headers)
    ).json()

    assert [n["title"] for n in data["outline"]] == chapters
    assert data["outline"][0]["start_time"] == pytest.approx(0.0)
    assert data["outline"][-1]["end_time"] == pytest.approx(1200.0)
    # The section index has to carry timestamps, not pages, for a recording.
    assert "元音字母" in data["section_index"]
    assert data["section_index"]["元音字母"][0] == pytest.approx(300.0)


@pytest.mark.asyncio
async def test_structured_outline_wins_over_rebuilding(client: AsyncClient) -> None:
    """When the pipeline did store chapters, they are used verbatim."""
    headers = await auth_header(client, email="vstored@example.com")
    uid = await _user_id(client, headers)
    stored = {
        "kind": "video",
        "duration": 900.0,
        "sections": [
            {"level": 1, "number": "1", "title": "开场与目标", "page_number": 0,
             "start_time": 0.0, "end_time": 300.0},
            {"level": 1, "number": "2", "title": "字母发音", "page_number": 0,
             "start_time": 300.0, "end_time": 900.0},
        ],
    }
    import json

    source_id = await _seed_video(
        uid,
        outline_json=json.dumps(stored, ensure_ascii=False),
        chunks=[(0.0, 30.0, "开场与目标"), (400.0, 430.0, "字母发音")],
    )

    data = (
        await client.get(f"/api/v1/sources/{source_id}/structure", headers=headers)
    ).json()

    assert [n["title"] for n in data["outline"]] == ["开场与目标", "字母发音"]
    assert data["duration"] == pytest.approx(900.0)


@pytest.mark.asyncio
async def test_regenerate_does_not_rename_a_recording(client: AsyncClient) -> None:
    """The mp4 keeps its file name; the generated headline lands on the summary."""
    headers = await auth_header(client, email="vtitle@example.com")
    uid = await _user_id(client, headers)
    source_id = await _seed_video(
        uid,
        filename="法语字母表.mp4",
        title="法语字母表.mp4",
        chunks=[(0.0, 30.0, "字母表")],
    )

    resp = await client.post(f"/api/v1/sources/{source_id}/regenerate", headers=headers)
    assert resp.status_code == 200, resp.text
    generated = resp.json()["title"]
    assert generated, "the summary must still carry the model's own title"

    after = (await client.get(f"/api/v1/sources/{source_id}", headers=headers)).json()
    assert after["title"] == "法语字母表.mp4"


@pytest.mark.asyncio
async def test_regenerate_still_retitles_a_document(client: AsyncClient) -> None:
    """The guard is specific to recordings — a PDF keeps the old behaviour."""
    headers = await auth_header(client, email="ptitle@example.com")
    uid = await _user_id(client, headers)
    source_id = uuid4()
    async with SessionLocal() as session:
        session.add(
            Source(
                id=source_id,
                user_id=uid,
                filename="chapter-01.pdf",
                content_type="application/pdf",
                kind="pdf",
                storage_key=f"{uid}/{source_id}/chapter-01.pdf",
                byte_size=1024,
                status="ready",
                title="chapter-01.pdf",
            )
        )
        session.add(
            DocumentChunk(
                source_id=source_id,
                user_id=uid,
                ordinal=0,
                content="Photosynthesis converts light energy into chemical energy.",
                page_number=1,
                content_type="body",
            )
        )
        await session.commit()

    resp = await client.post(f"/api/v1/sources/{source_id}/regenerate", headers=headers)
    assert resp.status_code == 200, resp.text
    after = (await client.get(f"/api/v1/sources/{source_id}", headers=headers)).json()
    assert after["title"] == resp.json()["title"]

# No teardown fixture on purpose: `client` already drops the whole schema after
# every test, and an autouse fixture would be torn down *after* it, i.e. against
# tables that no longer exist.
