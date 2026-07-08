from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import mysql_url, save_runtime_config
from app.database import get_db, init_db, refresh_engine
from app.models import AdminUser, Setting
from app.security import csrf_token, mask_secret, verify_csrf
from app.services.seed import seed_defaults
from app.templating import templates

router = APIRouter()


@router.get("/setup", response_class=HTMLResponse)
def setup_form(request: Request, db: Session = Depends(get_db)):
    settings = {s.key: (mask_secret(s.value) if s.is_secret else s.value) for s in db.scalars(select(Setting)).all()}
    return templates.TemplateResponse(request, "setup.html", {"settings": settings, "csrf_token": csrf_token(request)})


@router.post("/setup")
def setup_save(
    request: Request,
    csrf: str = Form(...),
    mysql_host: str = Form(...),
    mysql_port: str = Form("3306"),
    mysql_database: str = Form(...),
    mysql_user: str = Form(...),
    mysql_password: str = Form(""),
    discord_client_id: str = Form(""),
    discord_client_secret: str = Form(""),
    discord_redirect_uri: str = Form(""),
    admin_discord_id: str = Form(""),
    crawl_interval_hours: str = Form("6"),
    min_crawl_interval_minutes: str = Form("30"),
    thumbnail_cache_max_gb: str = Form("10"),
    site_name: str = Form("VRChat Avatar Watch"),
    misskey_instance_url: str = Form(""),
    misskey_token: str = Form(""),
    discord_webhook_admin: str = Form(""),
    discord_webhook_public: str = Form(""),
):
    verify_csrf(request, csrf)
    db_url = mysql_url(mysql_host, mysql_port, mysql_database, mysql_user, mysql_password)
    save_runtime_config({"database_url": db_url, "setup_complete": True, "site_name": site_name})
    refresh_engine()
    init_db()
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        seed_defaults(db)
        payload = {
            "site_name": (site_name, False),
            "mysql_host": (mysql_host, False),
            "mysql_port": (mysql_port, False),
            "mysql_database": (mysql_database, False),
            "mysql_user": (mysql_user, False),
            "mysql_password": (mysql_password, True),
            "discord_client_id": (discord_client_id, False),
            "discord_client_secret": (discord_client_secret, True),
            "discord_redirect_uri": (discord_redirect_uri, False),
            "admin_discord_id": (admin_discord_id, False),
            "crawl_interval_hours": (crawl_interval_hours, False),
            "min_crawl_interval_minutes": (min_crawl_interval_minutes, False),
            "thumbnail_cache_max_gb": (thumbnail_cache_max_gb, False),
            "misskey_instance_url": (misskey_instance_url, False),
            "misskey_token": (misskey_token, True),
            "discord_webhook_admin": (discord_webhook_admin, True),
            "discord_webhook_public": (discord_webhook_public, True),
        }
        for key, (value, is_secret) in payload.items():
            setting = db.scalar(select(Setting).where(Setting.key == key))
            if not setting:
                setting = Setting(key=key, is_secret=is_secret)
                db.add(setting)
            setting.value = value
            setting.is_secret = is_secret
        if admin_discord_id and not db.scalar(select(AdminUser).where(AdminUser.discord_id == admin_discord_id)):
            db.add(AdminUser(discord_id=admin_discord_id))
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin", status_code=303)
