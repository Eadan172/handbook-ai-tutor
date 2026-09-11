from __future__ import annotations

from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import decode_access_token
from app.models.user import User

bearer = HTTPBearer(auto_error=False)


async def _user_from_token(db: AsyncSession, raw_token: str) -> User:
    try:
        payload = decode_access_token(raw_token)
        user_id = UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return await _user_from_token(db, creds.credentials)


async def get_current_user_allow_query_token(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    token: str | None = Query(
        default=None,
        description="Same JWT as the Authorization header. Needed for <iframe>/<embed>, "
        "which cannot set request headers.",
    ),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Auth that also accepts ?token=..., for browser-native viewers of binary files."""
    raw = creds.credentials if creds and creds.credentials else token
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return await _user_from_token(db, raw)
