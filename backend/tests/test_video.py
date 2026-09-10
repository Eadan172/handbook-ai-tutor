from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header
from tests.helpers import tiny_mp4_bytes


@pytest.mark.asyncio
async def test_video_mock_stt_pipeline(client: AsyncClient) -> None:
    headers = await auth_header(client, email="video@example.com")
    files = {"file": ("lesson.mp4", tiny_mp4_bytes(), "video/mp4")}
    resp = await client.post("/api/v1/sources/upload", headers=headers, files=files)
    assert resp.status_code == 200, resp.text
    source_id = resp.json()["id"]
    status = "queued"
    for _ in range(100):
        got = await client.get(f"/api/v1/sources/{source_id}", headers=headers)
        status = got.json()["status"]
        if status in {"ready", "failed"}:
            break
        await asyncio.sleep(0.2)
    assert status == "ready", got.text
    retrieve = await client.post(
        f"/api/v1/sources/{source_id}/retrieve",
        headers=headers,
        json={"query": "photosynthesis chlorophyll", "top_k": 3},
    )
    assert retrieve.status_code == 200, retrieve.text
    cites = retrieve.json()["citations"]
    assert cites
    assert cites[0]["start_time"] is not None or "photosynthesis" in cites[0]["quote"].lower()
