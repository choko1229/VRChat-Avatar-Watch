from __future__ import annotations

import asyncio
import threading

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.crawler.booth import BoothCrawler
from app.crawler.parser import parse_item_detail
from app.database import SessionLocal, get_db
from app.models import Avatar, ErrorLog, Item, ItemAvatarRelation, PriceHistory, RankingMetric
from app.security import csrf_token, current_user, require_user, verify_csrf
from app.services.item_service import free_items, latest_items, sale_items, tool_items
from app.services.search_service import search_items
from app.services.watch_service import (
    dashboard_for_user,
    is_avatar_watched,
    is_item_favorited,
    is_shop_watched,
    set_notification_setting,
    toggle_avatar_watch,
    toggle_item_favorite,
    toggle_shop_watch,
)
from app.templating import templates

router = APIRouter()
_detail_fetch_lock = threading.Lock()
_detail_fetching_item_ids: set[int] = set()


def increment_item_metric(metric: RankingMetric, item: Item) -> None:
    metric.view_count = (metric.view_count or 0) + 1
    if item.is_on_sale:
        metric.sale_view_count = (metric.sale_view_count or 0) + 1
    if item.is_free:
        metric.free_view_count = (metric.free_view_count or 0) + 1


def _run_item_detail_fetch(item_id: int) -> None:
    db = SessionLocal()
    crawler = BoothCrawler(db)
    try:
        item = db.get(Item, item_id)
        if not item or item.description or not item.item_url:
            return
        if not asyncio.run(crawler.robots_allows_url(item.item_url)):
            db.add(ErrorLog(source="item_detail_fetch", level="warning", message="robots.txt does not allow item detail fetch", detail=item.item_url))
            db.commit()
            return
        response = asyncio.run(crawler.fetch(item.item_url))
        if response.status_code in {403, 429} or response.status_code >= 500:
            db.add(
                ErrorLog(
                    source="item_detail_fetch",
                    level="warning",
                    message="BOOTH detail page returned a throttling or server status",
                    detail=f"status_code={response.status_code} url={item.item_url}",
                )
            )
            db.commit()
            return
        response.raise_for_status()
        crawler.upsert_items([parse_item_detail(response.text, item.item_url)])
    except Exception as exc:
        db.rollback()
        db.add(ErrorLog(source="item_detail_fetch", level="error", message="item detail fetch failed", detail=str(exc)[:2000]))
        db.commit()
    finally:
        asyncio.run(crawler.close())
        db.close()
        with _detail_fetch_lock:
            _detail_fetching_item_ids.discard(item_id)


def ensure_item_detail_fetch_started(item: Item) -> None:
    if item.description or not item.item_url:
        return
    with _detail_fetch_lock:
        if item.id in _detail_fetching_item_ids:
            return
        _detail_fetching_item_ids.add(item.id)
    threading.Thread(target=_run_item_detail_fetch, args=(item.id,), daemon=True).start()


@router.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "latest_items": latest_items(db),
            "sale_items": sale_items(db),
            "free_items": free_items(db),
            "ranking_items": [],
            "user": current_user(request, db),
        },
    )


@router.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = "", db: Session = Depends(get_db)):
    items = search_items(db, q)
    template = "items/partial_grid.html" if request.headers.get("HX-Request") else "search.html"
    return templates.TemplateResponse(request, template, {"items": items, "q": q, "avatars": db.scalars(select(Avatar)).all(), "user": current_user(request, db)})


@router.get("/sales", response_class=HTMLResponse)
def sales(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "sales.html", {"items": sale_items(db, 80), "user": current_user(request, db)})


@router.get("/free", response_class=HTMLResponse)
def free(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "free.html", {"items": free_items(db, 80), "user": current_user(request, db)})


@router.get("/tools", response_class=HTMLResponse)
def tools(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "tools.html", {"items": tool_items(db, 80), "user": current_user(request, db)})


@router.get("/items/{item_id}", response_class=HTMLResponse)
def item_detail(request: Request, item_id: int, db: Session = Depends(get_db)):
    item = db.scalar(
        select(Item)
        .where(Item.id == item_id)
        .options(selectinload(Item.tags), selectinload(Item.avatar_relations).selectinload(ItemAvatarRelation.avatar), selectinload(Item.price_histories))
    )
    if not item:
        raise HTTPException(status_code=404, detail="商品が見つかりません")
    ensure_item_detail_fetch_started(item)
    metric = db.scalar(select(RankingMetric).where(RankingMetric.item_id == item.id))
    if not metric:
        metric = RankingMetric(item_id=item.id)
        db.add(metric)
    increment_item_metric(metric, item)
    db.commit()
    user = current_user(request, db)
    related = db.scalars(select(Item).where(Item.id != item.id).limit(8)).all()
    return templates.TemplateResponse(
        request,
        "items/detail.html",
        {
            "item": item,
            "related_items": related,
            "user": user,
            "csrf_token": csrf_token(request),
            "is_favorited": is_item_favorited(db, user, item),
            "is_shop_watched": is_shop_watched(db, user, item.shop),
        },
    )


@router.get("/items/{item_id}/description", response_class=HTMLResponse)
def item_description(request: Request, item_id: int, db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="item not found")
    if not item.description:
        ensure_item_detail_fetch_started(item)
    return templates.TemplateResponse(request, "items/description_panel.html", {"item": item})


@router.post("/items/{item_id}/favorite")
def item_favorite(request: Request, item_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    verify_csrf(request, csrf)
    item = db.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="item not found")
    toggle_item_favorite(db, user, item)
    return RedirectResponse(f"/items/{item.id}", status_code=303)


@router.post("/items/{item_id}/shop-watch")
def item_shop_watch(request: Request, item_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    verify_csrf(request, csrf)
    item = db.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="item not found")
    if not item.shop:
        raise HTTPException(status_code=400, detail="shop is not linked to this item")
    toggle_shop_watch(db, user, item.shop)
    return RedirectResponse(f"/items/{item.id}", status_code=303)


@router.get("/avatars/{slug}", response_class=HTMLResponse)
def avatar_detail(request: Request, slug: str, db: Session = Depends(get_db)):
    avatar = db.scalar(select(Avatar).where(Avatar.slug == slug))
    if not avatar:
        raise HTTPException(status_code=404, detail="アバターが見つかりません")
    stmt = (
        select(Item)
        .join(ItemAvatarRelation, ItemAvatarRelation.item_id == Item.id)
        .where(ItemAvatarRelation.avatar_id == avatar.id, ItemAvatarRelation.match_type != "excluded")
        .order_by(Item.updated_at.desc())
    )
    items = db.scalars(stmt).unique().all()
    category_counts = db.execute(
        select(Item.category, func.count(Item.id))
        .join(ItemAvatarRelation, ItemAvatarRelation.item_id == Item.id)
        .where(ItemAvatarRelation.avatar_id == avatar.id, ItemAvatarRelation.match_type != "excluded")
        .group_by(Item.category)
    ).all()
    user = current_user(request, db)
    return templates.TemplateResponse(
        request,
        "avatars/detail.html",
        {
            "avatar": avatar,
            "items": items,
            "sale_count": sum(1 for item in items if item.is_on_sale),
            "free_count": sum(1 for item in items if item.is_free),
            "category_counts": category_counts,
            "user": user,
            "csrf_token": csrf_token(request),
            "is_watched": is_avatar_watched(db, user, avatar),
        },
    )


@router.post("/avatars/{slug}/watch")
def avatar_watch(request: Request, slug: str, csrf: str = Form(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    verify_csrf(request, csrf)
    avatar = db.scalar(select(Avatar).where(Avatar.slug == slug))
    if not avatar:
        raise HTTPException(status_code=404, detail="avatar not found")
    toggle_avatar_watch(db, user, avatar)
    return RedirectResponse(f"/avatars/{avatar.slug}", status_code=303)


@router.get("/me", response_class=HTMLResponse)
def me(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    data = dashboard_for_user(db, user) if user else {}
    return templates.TemplateResponse(request, "me.html", {"user": user, "csrf_token": csrf_token(request), **data})


@router.post("/me/settings")
def me_settings(
    request: Request,
    csrf: str = Form(...),
    notify_sale: str | None = Form(None),
    notify_free: str | None = Form(None),
    notify_new: str | None = Form(None),
    notify_price_change: str | None = Form(None),
    min_discount_rate: str = Form("0"),
    nsfw_enabled: str | None = Form(None),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    verify_csrf(request, csrf)
    try:
        discount = int(min_discount_rate)
    except ValueError:
        discount = 0
    set_notification_setting(
        db,
        user,
        notify_sale=notify_sale == "on",
        notify_free=notify_free == "on",
        notify_new=notify_new == "on",
        notify_price_change=notify_price_change == "on",
        min_discount_rate=discount,
        nsfw_enabled=nsfw_enabled == "on",
    )
    return RedirectResponse("/me", status_code=303)
