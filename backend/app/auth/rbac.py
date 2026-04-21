from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Membership, User
from app.db.session import get_session
from app.auth.deps import require_user  # single source of truth for JWT parsing
from app.auth.deps import require_org_context


ROLE_RANK: dict[str, int] = {
    "viewer": 10,
    "reviewer": 20,
    "admin": 30,
}


def _rank(role: str | None) -> int:
    return ROLE_RANK.get((role or "").strip().lower(), 0)


@dataclass(frozen=True)
class OrgContext:
    org_id: UUID
    user: User
    membership: Membership


async def require_membership(
    *,
    org_id: UUID,
    user: User = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> OrgContext:
    m = (
        (await session.execute(select(Membership).where(Membership.user_id == user.id).where(Membership.org_id == org_id)))
        .scalars()
        .first()
    )
    if not m:
        raise HTTPException(status_code=403, detail="Not a member of org")
    return OrgContext(org_id=org_id, user=user, membership=m)


async def require_membership_header(
    org_id: UUID = Depends(require_org_context),
    user: User = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> OrgContext:
    return await require_membership(org_id=org_id, user=user, session=session)


def require_org_role(min_role: str):
    min_rank = _rank(min_role)
    if min_rank <= 0:
        raise ValueError("Unknown min_role")

    async def _dep(ctx: OrgContext = Depends(require_membership)) -> OrgContext:
        if _rank(ctx.membership.role) < min_rank:
            raise HTTPException(status_code=403, detail=f"{min_role} role required")
        return ctx

    return _dep


def require_org_role_header(min_role: str):
    min_rank = _rank(min_role)
    if min_rank <= 0:
        raise ValueError("Unknown min_role")

    async def _dep(ctx: OrgContext = Depends(require_membership_header)) -> OrgContext:
        if _rank(ctx.membership.role) < min_rank:
            raise HTTPException(status_code=403, detail=f"{min_role} role required")
        return ctx

    return _dep

