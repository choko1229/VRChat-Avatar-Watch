from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.discord import discord_login_url, exchange_discord_user, get_setting, upsert_user_from_discord
from app.database import get_db

router = APIRouter()


@router.get("/login")
def login(request: Request, db: Session = Depends(get_db)):
    return RedirectResponse(discord_login_url(request, db))


@router.get("/auth/discord/callback")
async def callback(request: Request, code: str, state: str, db: Session = Depends(get_db)):
    if request.session.get("oauth_state") != state:
        raise HTTPException(status_code=400, detail="OAuth stateが一致しません")
    payload = await exchange_discord_user(db, code, get_setting(db, "discord_redirect_uri"))
    user = upsert_user_from_discord(db, payload)
    request.session["user_id"] = user.id
    return RedirectResponse("/me", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
