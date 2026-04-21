from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import decode_access_token
from app.db.models import Membership, User
from app.db.session import get_session


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2:
        return None
    if parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


async def require_user(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User:
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    try:
        claims = decode_access_token(token)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=401, detail="Invalid token")
    u = (await session.execute(select(User).where(User.id == UUID(claims.sub)))).scalars().first()
    if not u:
        raise HTTPException(status_code=401, detail="Unknown user")
    return u


async def require_org_context(
    user: User = Depends(require_user),
    x_org_id: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> UUID:
    memberships = (await session.execute(select(Membership).where(Membership.user_id == user.id))).scalars().all()
    if not memberships:
        raise HTTPException(status_code=403, detail="User has no org memberships")
    if x_org_id:
        try:
            oid = UUID(x_org_id)
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="Invalid X-Org-Id")
        if not any(m.org_id == oid for m in memberships):
            raise HTTPException(status_code=403, detail="Not a member of org")
        return oid
    return memberships[0].org_id

