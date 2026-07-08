from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_config, mysql_url, save_runtime_config
from app.database import get_db, refresh_engine
from app.models import Setting
from app.security import csrf_token, mask_secret, verify_csrf
from app.services.setup_service import SetupError, SetupSettings, create_tables_and_seed, validate_setup_input
from app.templating import templates

router = APIRouter()


@router.get("/setup", response_class=HTMLResponse)
def setup_form(request: Request, db: Session = Depends(get_db)):
    if get_config().setup_complete:
        return RedirectResponse("/", status_code=303)
    settings = {s.key: (mask_secret(s.value) if s.is_secret else s.value) for s in db.scalars(select(Setting)).all()}
    return templates.TemplateResponse(request, "setup.html", {"settings": settings, "csrf_token": csrf_token(request), "error": None, "form": {}})


@router.post("/setup")
def setup_save(
    request: Request,
    csrf: str = Form(...),
    mysql_host: str = Form(...),
    mysql_port: str = Form("3306"),
    mysql_database: str = Form(...),
    mysql_user: str = Form(...),
    mysql_password: str = Form(""),
    discord_client_id: str = Form(...),
    discord_client_secret: str = Form(...),
    discord_redirect_uri: str = Form(...),
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
    if get_config().setup_complete:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="セットアップは完了済みです")
    verify_csrf(request, csrf)
    settings = SetupSettings(
        site_name=site_name,
        mysql_host=mysql_host,
        mysql_port=mysql_port,
        mysql_database=mysql_database,
        mysql_user=mysql_user,
        mysql_password=mysql_password,
        discord_client_id=discord_client_id,
        discord_client_secret=discord_client_secret,
        discord_redirect_uri=discord_redirect_uri,
        admin_discord_id=admin_discord_id,
        crawl_interval_hours=crawl_interval_hours,
        min_crawl_interval_minutes=min_crawl_interval_minutes,
        thumbnail_cache_max_gb=thumbnail_cache_max_gb,
        misskey_instance_url=misskey_instance_url,
        misskey_token=misskey_token,
        discord_webhook_admin=discord_webhook_admin,
        discord_webhook_public=discord_webhook_public,
    )
    form = {
        "site_name": site_name,
        "mysql_host": mysql_host,
        "mysql_port": mysql_port,
        "mysql_database": mysql_database,
        "mysql_user": mysql_user,
        "discord_client_id": discord_client_id,
        "discord_redirect_uri": discord_redirect_uri,
        "admin_discord_id": admin_discord_id,
        "crawl_interval_hours": crawl_interval_hours,
        "min_crawl_interval_minutes": min_crawl_interval_minutes,
        "thumbnail_cache_max_gb": thumbnail_cache_max_gb,
        "misskey_instance_url": misskey_instance_url,
    }
    try:
        validate_setup_input(settings)
        db_url = mysql_url(mysql_host, mysql_port, mysql_database, mysql_user, mysql_password)
        create_tables_and_seed(db_url, settings)
    except SetupError as exc:
        return templates.TemplateResponse(
            request,
            "setup.html",
            {"settings": {}, "csrf_token": csrf_token(request), "error": str(exc), "form": form},
            status_code=400,
        )
    save_runtime_config({"database_url": db_url, "setup_complete": True, "site_name": site_name})
    refresh_engine()
    return RedirectResponse("/login", status_code=303)
