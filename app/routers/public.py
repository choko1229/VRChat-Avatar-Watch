from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Avatar, Item, ItemAvatarRelation, PriceHistory, RankingMetric
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
    metric = db.scalar(select(RankingMetric).where(RankingMetric.item_id == item.id))
    if not metric:
        metric = RankingMetric(item_id=item.id)
        db.add(metric)
    metric.view_count += 1
    if item.is_on_sale:
        metric.sale_view_count += 1
    if item.is_free:
        metric.free_view_count += 1
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
