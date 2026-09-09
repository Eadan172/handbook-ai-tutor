from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header
from tests.helpers import minimal_pdf_bytes


@pytest.mark.asyncio
async def test_upload_enqueues_task(client: AsyncClient) -> None:
    headers = await auth_header(client)
    files = {"file": ("lesson.pdf", minimal_pdf_bytes(), "application/pdf")}
    resp = await client.post("/api/v1/sources/upload", headers=headers, files=files)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "pdf"
    assert body["task_id"]
    assert body["status"] in {"queued", "running", "ready", "failed"}

    task = await client.get(f"/api/v1/tasks/{body['task_id']}", headers=headers)
    assert task.status_code == 200
    assert task.json()["kind"] == "ingest"


@pytest.mark.asyncio
async def test_pdf_pipeline_completes(client: AsyncClient) -> None:
    headers = await auth_header(client, email="pdf@example.com")
    files = {"file": ("lesson.pdf", minimal_pdf_bytes(), "application/pdf")}
    resp = await client.post("/api/v1/sources/upload", headers=headers, files=files)
    assert resp.status_code == 200, resp.text
    source_id = resp.json()["id"]

    status = "queued"
    for _ in range(80):
        got = await client.get(f"/api/v1/sources/{source_id}", headers=headers)
        status = got.json()["status"]
        if status in {"ready", "failed"}:
            break
        await asyncio.sleep(0.15)
    assert status == "ready", got.text

    summary = await client.get(f"/api/v1/sources/{source_id}/summary", headers=headers)
    assert summary.status_code == 200, summary.text
    assert summary.json()["overview"]

    knowledge = await client.get(f"/api/v1/sources/{source_id}/knowledge", headers=headers)
    assert knowledge.status_code == 200
    assert len(knowledge.json()) >= 1
