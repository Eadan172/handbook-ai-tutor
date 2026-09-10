from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header


@pytest.mark.asyncio
async def test_register_login_me(client: AsyncClient) -> None:
    headers = await auth_header(client)
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == "ada@example.com"

    bad = await client.post(
        "/api/v1/auth/login", json={"email": "ada@example.com", "password": "wrongpass"}
    )
    assert bad.status_code == 401

    ok = await client.post(
        "/api/v1/auth/login", json={"email": "ada@example.com", "password": "password123"}
    )
    assert ok.status_code == 200
    assert ok.json()["access_token"]


@pytest.mark.asyncio
async def test_unauthenticated(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/sources")
    assert resp.status_code == 401
