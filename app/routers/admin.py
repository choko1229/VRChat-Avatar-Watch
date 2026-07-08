from __future__ import annotations

import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.crawler.booth import BoothCrawler, validate_crawl_target
from app.crawler.parser import parse_item_detail, parse_search_results, summarize_parsed_items
from app.database import SessionLocal, get_db
from app.models import Avatar, CrawlLog, CrawlTarget, ErrorLog, Item, ItemAvatarRelation, Setting, Shop, Tool, User
from app.security import csrf_token, mask_secret, require_admin, verify_csrf
from app.services.admin_service import create_manual_item, parse_tags, save_setting, save_tool, set_avatar_relation, update_manual_item
from app.templating import templates

router = APIRouter(prefix="/admin")


def run_crawl_target_background(target_id: int, force: bool = False) -> None:
    db = SessionLocal()
    crawler = BoothCrawler(db)
    try:
        target = db.get(CrawlTarget, target_id)
        if target and target.is_active:
            asyncio.run(crawler.crawl_target(target, force=force))
    finally:
        asyncio.run(crawler.close())
        db.close()


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    counts = {
        "items": db.scalar(select(func.count(Item.id))) or 0,
        "avatars": db.scalar(select(func.count(Avatar.id))) or 0,
        "sales": db.scalar(select(func.count(Item.id)).where(Item.is_on_sale.is_(True))) or 0,
        "free": db.scalar(select(func.count(Item.id)).where(Item.is_free.is_(True))) or 0,
    }
    logs = db.scalars(select(CrawlLog).order_by(CrawlLog.started_at.desc()).limit(10)).all()
    return templates.TemplateResponse(request, "admin/dashboard.html", {"user": user, "counts": counts, "logs": logs, "csrf_token": csrf_token(request)})


@router.get("/items", response_class=HTMLResponse)
def items(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    return templates.TemplateResponse(
        request,
        "admin/items.html",
        {
            "user": user,
            "items": db.scalars(select(Item).order_by(Item.updated_at.desc()).limit(200)).all(),
            "avatars": db.scalars(select(Avatar).where(Avatar.is_active.is_(True))).all(),
            "csrf_token": csrf_token(request),
        },
    )


@router.post("/items")
def create_item(
    request: Request,
    csrf: str = Form(...),
    title: str = Form(...),
    item_url: str = Form(...),
    description: str = Form(""),
    image_url: str = Form(""),
    shop_name: str = Form(""),
    shop_url: str = Form(""),
    current_price: str = Form(""),
    category: str = Form(""),
    tags: str = Form(""),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    verify_csrf(request, csrf)
    price = int(current_price) if current_price.strip() else None
    item = create_manual_item(
        db,
        title=title,
        item_url=item_url,
        description=description,
        image_url=image_url,
        shop_name=shop_name,
        shop_url=shop_url,
        current_price=price,
        category=category,
        tags=parse_tags(tags),
    )
    return RedirectResponse(f"/admin/items/{item.id}", status_code=303)


@router.get("/items/{item_id}", response_class=HTMLResponse)
def item_edit(request: Request, item_id: int, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    item = db.scalar(
        select(Item)
        .where(Item.id == item_id)
        .options(selectinload(Item.tags), selectinload(Item.avatar_relations).selectinload(ItemAvatarRelation.avatar), selectinload(Item.price_histories))
    )
    if not item:
        raise HTTPException(status_code=404, detail="商品が見つかりません")
    return templates.TemplateResponse(
        request,
        "admin/item_edit.html",
        {
            "user": user,
            "item": item,
            "avatars": db.scalars(select(Avatar).where(Avatar.is_active.is_(True))).all(),
            "csrf_token": csrf_token(request),
        },
    )


@router.post("/items/{item_id}")
def item_update(
    request: Request,
    item_id: int,
    csrf: str = Form(...),
    title: str = Form(...),
    item_url: str = Form(...),
    description: str = Form(""),
    image_url: str = Form(""),
    shop_name: str = Form(""),
    shop_url: str = Form(""),
    current_price: str = Form(""),
    category: str = Form(""),
    tags: str = Form(""),
    is_free: str | None = Form(None),
    is_on_sale: str | None = Form(None),
    is_nsfw: str | None = Form(None),
    is_tool: str | None = Form(None),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    verify_csrf(request, csrf)
    item = db.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="商品が見つかりません")
    update_manual_item(
        db,
        item,
        title=title,
        item_url=item_url,
        description=description,
        image_url=image_url,
        shop_name=shop_name,
        shop_url=shop_url,
        current_price=int(current_price) if current_price.strip() else None,
        category=category,
        tags=parse_tags(tags),
        is_free=is_free == "on",
        is_on_sale=is_on_sale == "on",
        is_nsfw=is_nsfw == "on",
        is_tool=is_tool == "on",
    )
    return RedirectResponse(f"/admin/items/{item.id}", status_code=303)


@router.post("/items/{item_id}/avatar-relations")
def item_avatar_update(
    request: Request,
    item_id: int,
    csrf: str = Form(...),
    avatar_id: int = Form(...),
    match_type: str = Form(...),
    match_reason: str = Form(""),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    verify_csrf(request, csrf)
    item = db.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="商品が見つかりません")
    set_avatar_relation(db, item, avatar_id, match_type, match_reason)
    return RedirectResponse(f"/admin/items/{item.id}", status_code=303)


@router.get("/avatars", response_class=HTMLResponse)
def avatars(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    return templates.TemplateResponse(request, "admin/avatars.html", {"user": user, "avatars": db.scalars(select(Avatar)).all(), "csrf_token": csrf_token(request)})


@router.post("/avatars/{avatar_id}")
def update_avatar(request: Request, avatar_id: int, csrf: str = Form(...), image_url: str = Form(""), booth_url: str = Form(""), db: Session = Depends(get_db)):
    require_admin(request, db)
    verify_csrf(request, csrf)
    avatar = db.get(Avatar, avatar_id)
    if avatar:
        avatar.image_url = image_url
        avatar.booth_url = booth_url
        db.commit()
    return RedirectResponse("/admin/avatars", status_code=303)


@router.get("/tools", response_class=HTMLResponse)
def tools(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    return templates.TemplateResponse(request, "admin/tools.html", {"user": user, "tools": db.scalars(select(Tool)).all(), "csrf_token": csrf_token(request)})


@router.post("/tools")
def upsert_tool(
    request: Request,
    csrf: str = Form(...),
    tool_id: str = Form(""),
    name: str = Form(...),
    slug: str = Form(...),
    description: str = Form(""),
    booth_url: str = Form(""),
    image_url: str = Form(""),
    search_keywords: str = Form(""),
    exclude_keywords: str = Form(""),
    is_active: str | None = Form(None),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    verify_csrf(request, csrf)
    tool = db.get(Tool, int(tool_id)) if tool_id.strip() else None
    save_tool(
        db,
        tool,
        name=name,
        slug=slug,
        description=description,
        booth_url=booth_url,
        image_url=image_url,
        search_keywords=search_keywords,
        exclude_keywords=exclude_keywords,
        is_active=is_active == "on",
    )
    return RedirectResponse("/admin/tools", status_code=303)


@router.get("/shops", response_class=HTMLResponse)
def shops(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    return templates.TemplateResponse(request, "admin/shops.html", {"user": user, "shops": db.scalars(select(Shop)).all(), "csrf_token": csrf_token(request)})


@router.post("/shops/{shop_id}")
def update_shop(
    request: Request,
    shop_id: int,
    csrf: str = Form(...),
    is_watch_enabled: str | None = Form(None),
    is_excluded: str | None = Form(None),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    verify_csrf(request, csrf)
    shop = db.get(Shop, shop_id)
    if shop:
        shop.is_watch_enabled = is_watch_enabled == "on"
        shop.is_excluded = is_excluded == "on"
        db.commit()
    return RedirectResponse("/admin/shops", status_code=303)


@router.get("/keywords", response_class=HTMLResponse)
def keywords(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    targets = db.scalars(select(CrawlTarget).order_by(CrawlTarget.created_at.desc())).all()
    return templates.TemplateResponse(request, "admin/keywords.html", {"user": user, "targets": targets, "csrf_token": csrf_token(request)})


@router.post("/keywords")
def add_keyword(request: Request, csrf: str = Form(...), target_type: str = Form(...), target_value: str = Form(...), db: Session = Depends(get_db)):
    require_admin(request, db)
    verify_csrf(request, csrf)
    validation_error = validate_crawl_target(target_type, target_value)
    if validation_error:
        raise HTTPException(status_code=400, detail=validation_error)
    db.add(CrawlTarget(target_type=target_type, target_value=target_value))
    db.commit()
    return RedirectResponse("/admin/keywords", status_code=303)


@router.get("/crawl", response_class=HTMLResponse)
def crawl(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    return templates.TemplateResponse(
        request,
        "admin/crawl.html",
        {
            "user": user,
            "targets": db.scalars(select(CrawlTarget).where(CrawlTarget.is_active.is_(True))).all(),
            "logs": db.scalars(select(CrawlLog).order_by(CrawlLog.started_at.desc()).limit(50)).all(),
            "running_logs": db.scalars(select(CrawlLog).where(CrawlLog.status == "running").order_by(CrawlLog.started_at.desc()).limit(10)).all(),
            "csrf_token": csrf_token(request),
        },
    )


@router.get("/crawl/status", response_class=HTMLResponse)
def crawl_status(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    return templates.TemplateResponse(
        request,
        "admin/crawl_status.html",
        {
            "running_logs": db.scalars(select(CrawlLog).where(CrawlLog.status == "running").order_by(CrawlLog.started_at.desc()).limit(10)).all(),
            "logs": db.scalars(select(CrawlLog).order_by(CrawlLog.started_at.desc()).limit(50)).all(),
        },
    )


@router.post("/crawl/run")
def crawl_run(
    background_tasks: BackgroundTasks,
    request: Request,
    csrf: str = Form(...),
    target_id: int = Form(...),
    force: str | None = Form(None),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    verify_csrf(request, csrf)
    target = db.get(CrawlTarget, target_id)
    if target and target.is_active:
        background_tasks.add_task(run_crawl_target_background, target.id, force == "on")
    return RedirectResponse("/admin/crawl", status_code=303)


@router.post("/crawl/dry-run", response_class=HTMLResponse)
def crawl_dry_run(
    request: Request,
    csrf: str = Form(...),
    target_id: int = Form(...),
    force: str | None = Form(None),
    db: Session = Depends(get_db),
):
    user = require_admin(request, db)
    verify_csrf(request, csrf)
    target = db.get(CrawlTarget, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="クロール対象が見つかりません")
    crawler = BoothCrawler(db)
    try:
        result = asyncio.run(crawler.preview_target(target, force=force == "on"))
    finally:
        asyncio.run(crawler.close())
    return templates.TemplateResponse(
        request,
        "admin/crawl_dry_run.html",
        {
            "user": user,
            "target": target,
            "result": result,
            "csrf_token": csrf_token(request),
        },
    )


@router.post("/crawl/preview", response_class=HTMLResponse)
def crawl_preview(
    request: Request,
    csrf: str = Form(...),
    html: str = Form(...),
    source_url: str = Form("https://booth.pm/ja/search/VRChat"),
    page_type: str = Form("search"),
    db: Session = Depends(get_db),
):
    user = require_admin(request, db)
    verify_csrf(request, csrf)
    parsed = parse_search_results(html, source_url) if page_type == "search" else [parse_item_detail(html, source_url)]
    return templates.TemplateResponse(
        request,
        "admin/crawl_preview.html",
        {
            "user": user,
            "items": parsed,
            "summary": summarize_parsed_items(parsed),
            "csrf_token": csrf_token(request),
        },
    )


@router.get("/logs", response_class=HTMLResponse)
def logs(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    return templates.TemplateResponse(request, "admin/logs.html", {"user": user, "crawl_logs": db.scalars(select(CrawlLog).order_by(CrawlLog.started_at.desc()).limit(100)).all(), "error_logs": db.scalars(select(ErrorLog).order_by(ErrorLog.created_at.desc()).limit(100)).all()})


@router.get("/users", response_class=HTMLResponse)
def users(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    return templates.TemplateResponse(request, "admin/users.html", {"user": user, "users": db.scalars(select(User).order_by(User.created_at.desc())).all()})


@router.get("/settings", response_class=HTMLResponse)
def settings(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    rows = db.scalars(select(Setting).order_by(Setting.key)).all()
    return templates.TemplateResponse(request, "admin/settings.html", {"user": user, "settings": rows, "mask_secret": mask_secret, "csrf_token": csrf_token(request)})


@router.post("/settings")
def save_settings(
    request: Request,
    csrf: str = Form(...),
    crawl_interval_hours: str = Form("6"),
    thumbnail_cache_max_gb: str = Form("10"),
    min_crawl_interval_minutes: str = Form("30"),
    max_search_pages_per_crawl: str = Form("5"),
    max_detail_pages_per_crawl: str = Form("20"),
    misskey_instance_url: str = Form(""),
    misskey_token: str = Form(""),
    discord_webhook_admin: str = Form(""),
    discord_webhook_public: str = Form(""),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    verify_csrf(request, csrf)
    save_setting(db, "crawl_interval_hours", crawl_interval_hours)
    save_setting(db, "min_crawl_interval_minutes", min_crawl_interval_minutes)
    save_setting(db, "max_search_pages_per_crawl", max_search_pages_per_crawl)
    save_setting(db, "max_detail_pages_per_crawl", max_detail_pages_per_crawl)
    save_setting(db, "thumbnail_cache_max_gb", thumbnail_cache_max_gb)
    save_setting(db, "misskey_instance_url", misskey_instance_url)
    if misskey_token:
        save_setting(db, "misskey_token", misskey_token, True)
    if discord_webhook_admin:
        save_setting(db, "discord_webhook_admin", discord_webhook_admin, True)
    if discord_webhook_public:
        save_setting(db, "discord_webhook_public", discord_webhook_public, True)
    return RedirectResponse("/admin/settings", status_code=303)
