import secrets

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import AnonymousUser


def new_token() -> str:
    return secrets.token_urlsafe(48)


def get_current_user(
    x_session_token: str = Header(default=""), db: Session = Depends(get_db)
) -> AnonymousUser:
    if not x_session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少匿名会话令牌")
    user = db.scalar(select(AnonymousUser).where(AnonymousUser.token == x_session_token))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="匿名会话已失效")
    return user

