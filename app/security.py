from __future__ import annotations

import hmac
import secrets
from urllib.parse import urlparse

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AdminUser, User


SAFE_EXTERNAL_HOSTS = {"booth.pm", "www.booth.pm"}


def mask_secret(value: str | None) -> str:
    if not value:
        return "未設定"
    return "configured"


def is_safe_external_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in {"https", "http"} and bool(parsed.netloc)


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def verify_csrf(request: Request, token: str | None) -> None:
    expected = request.session.get("csrf_token")
    if not expected or not token or not hmac.compare_digest(expected, token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token mismatch")


def current_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.get(User, int(user_id))


def require_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="ログインが必要です")
    return user


def is_admin(db: Session, user: User | None) -> bool:
    if not user:
        return False
    return db.scalar(select(AdminUser).where(AdminUser.discord_id == user.discord_id)) is not None


def require_admin(request: Request, db: Session) -> User:
    user = require_user(request, db)
    if not is_admin(db, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="管理者権限が必要です")
    return user
