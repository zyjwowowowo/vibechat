import secrets
from datetime import datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import AnonymousUser, DeviceSession

password_hasher = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)


def new_token() -> str:
    return secrets.token_urlsafe(48)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def get_current_user(
    x_session_token: str = Header(default=""), authorization: str = Header(default=""), db: Session = Depends(get_db)
) -> AnonymousUser:
    token = x_session_token or authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少会话令牌")
    device = db.scalar(
        select(DeviceSession).where(DeviceSession.token == token, DeviceSession.revoked_at.is_(None))
    )
    user = db.get(AnonymousUser, device.user_id) if device else db.scalar(
        select(AnonymousUser).where(AnonymousUser.token == token)
    )
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="会话已失效")
    if device:
        device.last_seen_at = datetime.utcnow()
        db.commit()
    return user
