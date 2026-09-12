from __future__ import annotations

import asyncio
import json

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header
from tests.helpers import minimal_pdf_bytes


async def _wait_ready(client: AsyncClient, headers: dict, source_id: str) -> dict:
    got = None
    for _ in range(80):
        got = await client.get(f"/api/v1/sources/{source_id}", headers=headers)
        if got.json().get("status") in {"ready", "failed"}:
            return got.json()
        await asyncio.sleep(0.15)
    assert got is not None
    return got.json()


@pytest.mark.asyncio
async def test_task_events_sse_with_bearer(client: AsyncClient) -> None:
    headers = await auth_header(client, email="sse@example.com")
    files = {"file": ("lesson.pdf", minimal_pdf_bytes(), "application/pdf")}
    resp = await client.post("/api/v1/sources/upload", headers=headers, files=files)
    assert resp.status_code == 200, resp.text
    source = await _wait_ready(client, headers, resp.json()["id"])
    assert source["status"] == "ready"
    task_id = source["task_id"]
    assert task_id
    assert source.get("extraction_note") or source.get("task_message")

    events = await client.get(f"/api/v1/tasks/{task_id}/events", headers=headers)
    assert events.status_code == 200, events.text
    assert "text/event-stream" in events.headers.get("content-type", "")
    payloads = []
    for block in events.text.split("\n\n"):
        line = block.strip()
        if line.startswith("data:"):
            payloads.append(json.loads(line[5:].strip()))
    assert payloads
    assert payloads[-1]["status"] == "succeeded"
    assert payloads[-1]["id"] == task_id


@pytest.mark.asyncio
async def test_task_events_accepts_query_token(client: AsyncClient) -> None:
    headers = await auth_header(client, email="sseq@example.com")
    token = headers["Authorization"].split(" ", 1)[1]
    files = {"file": ("lesson.pdf", minimal_pdf_bytes(), "application/pdf")}
    resp = await client.post("/api/v1/sources/upload", headers=headers, files=files)
    source = await _wait_ready(client, headers, resp.json()["id"])
    task_id = source["task_id"]

    events = await client.get(f"/api/v1/tasks/{task_id}/events?token={token}")
    assert events.status_code == 200, events.text
    assert "succeeded" in events.text


@pytest.mark.asyncio
async def test_task_events_rejects_anonymous(client: AsyncClient) -> None:
    headers = await auth_header(client, email="ssex@example.com")
    files = {"file": ("lesson.pdf", minimal_pdf_bytes(), "application/pdf")}
    resp = await client.post("/api/v1/sources/upload", headers=headers, files=files)
    source = await _wait_ready(client, headers, resp.json()["id"])
    events = await client.get(f"/api/v1/tasks/{source['task_id']}/events")
    assert events.status_code == 401
