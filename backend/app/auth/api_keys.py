from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiKey, ApiKeyUsage
from app.db.session import get_session


def _now() -> datetime:
    return datetime.utcnow()


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_api_key(*, prefix: str = "oel") -> tuple[str, str, str]:
    """
    Returns (raw_key, prefix, key_hash).
    Raw key is only shown once.
    """
    token = secrets.token_urlsafe(32)
    raw = f"{prefix}_{token}"
    return raw, prefix, _hash_key(raw)


@dataclass(frozen=True)
class ApiKeyContext:
    org_id: UUID
    api_key: ApiKey


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    session: AsyncSession = Depends(get_session),
) -> ApiKeyContext:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    raw = x_api_key.strip()
    if len(raw) < 20:
        raise HTTPException(status_code=401, detail="Invalid API key")
    h = _hash_key(raw)
    row = (await session.execute(select(ApiKey).where(ApiKey.key_hash == h))).scalars().first()
    if not row or row.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    row.last_used_at = _now()
    await session.merge(row)
    session.add(
        ApiKeyUsage(
            api_key_id=row.id,
            org_id=row.org_id,
            path=str(request.url.path),
            method=str(request.method),
        )
    )
    await session.commit()
    return ApiKeyContext(org_id=row.org_id, api_key=row)

