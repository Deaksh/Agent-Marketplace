from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from passlib.context import CryptContext

from app.core.config import settings


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    # bcrypt ignores bytes after 72; explicitly truncate to avoid surprising runtime errors.
    p = (password or "")[:72]
    return pwd_context.hash(p)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        p = (password or "")[:72]
        return pwd_context.verify(p, password_hash)
    except Exception:  # noqa: BLE001
        return False


@dataclass(frozen=True)
class JwtClaims:
    sub: str
    email: str
    iat: int
    exp: int
    iss: str


def create_access_token(*, sub: str, email: str) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=int(settings.jwt_exp_minutes))
    payload: dict[str, Any] = {
        "sub": sub,
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "iss": settings.jwt_issuer,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> JwtClaims:
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],
        issuer=settings.jwt_issuer,
        options={"require": ["exp", "iat", "sub", "iss"]},
    )
    return JwtClaims(
        sub=str(payload["sub"]),
        email=str(payload.get("email") or ""),
        iat=int(payload["iat"]),
        exp=int(payload["exp"]),
        iss=str(payload["iss"]),
    )

