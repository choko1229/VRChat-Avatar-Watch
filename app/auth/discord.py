from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AdminUser, Setting, User

DISCORD_AUTH_URL = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_ME_URL = "https://discord.com/api/users/@me"


def get_setting(db: Session, key: str) -> str:
    setting = db.scalar(select(Setting).where(Setting.key == key))
    return setting.value if setting and setting.value else ""


def discord_login_url(request: Request, db: Session) -> str:
    client_id = get_setting(db, "discord_client_id")
    redirect_uri = get_setting(db, "discord_redirect_uri")
    if not client_id or not redirect_uri:
        raise HTTPException(status_code=400, detail="Discord OAuth設定が未完了です")
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    return f"{DISCORD_AUTH_URL}?{urlencode({'client_id': client_id, 'redirect_uri': redirect_uri, 'response_type': 'code', 'scope': 'identify', 'state': state})}"


async def exchange_discord_user(db: Session, code: str, redirect_uri: str) -> dict:
    client_id = get_setting(db, "discord_client_id")
    client_secret = get_setting(db, "discord_client_secret")
    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(status_code=400, detail="Discord OAuth設定が未完了です")
    async with httpx.AsyncClient(timeout=20) as client:
        token_res = await client.post(
            DISCORD_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_res.status_code >= 400:
            raise HTTPException(status_code=400, detail="Discord OAuth認証に失敗しました")
        access_token = token_res.json()["access_token"]
        me_res = await client.get(DISCORD_ME_URL, headers={"Authorization": f"Bearer {access_token}"})
        if me_res.status_code >= 400:
            raise HTTPException(status_code=400, detail="Discordユーザー情報の取得に失敗しました")
        return me_res.json()


def upsert_user_from_discord(db: Session, payload: dict) -> User:
    discord_id = payload["id"]
    user = db.scalar(select(User).where(User.discord_id == discord_id))
    avatar_hash = payload.get("avatar")
    avatar_url = f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.png" if avatar_hash else None
    if not user:
        user = User(discord_id=discord_id, username=payload.get("username", ""), display_name=payload.get("global_name"), avatar_url=avatar_url)
        db.add(user)
        db.flush()
    else:
        user.username = payload.get("username", user.username)
        user.display_name = payload.get("global_name")
        user.avatar_url = avatar_url
    if not db.scalar(select(AdminUser)):
        db.add(AdminUser(user_id=user.id, discord_id=discord_id))
    configured_admin = get_setting(db, "admin_discord_id")
    if configured_admin and configured_admin == discord_id and not db.scalar(select(AdminUser).where(AdminUser.discord_id == discord_id)):
        db.add(AdminUser(user_id=user.id, discord_id=discord_id))
    db.commit()
    return user
