from __future__ import annotations

import asyncio
import threading

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.crawler.booth import BoothCrawler, title_looks_truncated
from app.crawler.parser import parse_item_detail
from app.database import SessionLocal, get_db
from app.models import Avatar, ErrorLog, Item, ItemAvatarRelation, LibraryImportJob, PriceHistory, RankingMetric, User, now_utc
from app.security import csrf_token, current_user, require_user, verify_csrf
from app.services.item_service import free_items, latest_items, sale_items, tool_items
from app.services.library_service import import_owned_items, owned_items_for_user, related_items_for_owned_avatars
from app.services.ranking_service import ranking_items
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


def _needs_full_detail_fetch(item: Item) -> bool:
    # A missing description or a title BOOTH truncated with an ellipsis on
    # the search-card means we're only showing partial information - fetch
    # the actual detail page to get the full title/description before the
    # user reads (or a matcher judges) an incomplete version of either.
    return not item.description or title_looks_truncated(item.title)


def _run_item_detail_fetch(item_id: int) -> None:
    db = SessionLocal()
    crawler = BoothCrawler(db)
    try:
        item = db.get(Item, item_id)
        if not item or not item.item_url or not _needs_full_detail_fetch(item):
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
    if not item.item_url or not _needs_full_detail_fetch(item):
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
            "ranking_items": ranking_items(db),
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


@router.get("/avatars", response_class=HTMLResponse)
def avatars(request: Request, db: Session = Depends(get_db)):
    item_counts = (
        select(ItemAvatarRelation.avatar_id, func.count(ItemAvatarRelation.item_id).label("item_count"))
        .where(ItemAvatarRelation.match_type != "excluded")
        .group_by(ItemAvatarRelation.avatar_id)
        .subquery()
    )
    avatar_rows = db.execute(
        select(Avatar, func.coalesce(item_counts.c.item_count, 0))
        .outerjoin(item_counts, item_counts.c.avatar_id == Avatar.id)
        .where(Avatar.is_active.is_(True))
        .order_by(Avatar.name)
    ).all()
    return templates.TemplateResponse(
        request,
        "avatars/list.html",
        {"avatars": avatar_rows, "user": current_user(request, db)},
    )


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
    if user:
        data["owned_items"] = owned_items_for_user(db, user)
        data["related_by_avatar"] = related_items_for_owned_avatars(db, user)
    return templates.TemplateResponse(request, "me.html", {"user": user, "csrf_token": csrf_token(request), **data})


def run_library_import_background(job_id: int, user_id: int, html: str) -> None:
    # Runs independently of the crawl/reclassify background tasks - it only
    # ever touches this one user's UserOwnedItem rows and reads (never
    # writes) Avatar/AvatarAlias, so it doesn't need CRAWL_WRITE_LOCK and
    # won't queue up behind a long-running crawl or reclassify.
    db = SessionLocal()
    try:
        job = db.get(LibraryImportJob, job_id)
        if job is None:
            return
        job.status = "running"
        job.message = "取り込みを開始しました"
        db.commit()
        user = db.get(User, user_id)
        summary = import_owned_items(db, user, html, job)
        job.status = "success"
        job.parsed_count = summary["parsed"]
        job.imported_count = summary["imported"]
        job.matched_count = summary["matched"]
        job.message = f"完了: {summary['parsed']}件解析・新規{summary['imported']}件・アバター認識{summary['matched']}件"
        job.finished_at = now_utc()
        db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(LibraryImportJob, job_id)
        if job:
            job.status = "error"
            job.message = "取り込みに失敗しました"
            job.error_detail = str(exc)[:2000]
            job.finished_at = now_utc()
            db.commit()
    finally:
        db.close()


@router.post("/me/library/import")
def me_library_import(request: Request, csrf: str = Form(...), html: str = Form(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    verify_csrf(request, csrf)
    job = LibraryImportJob(user_id=user.id, status="queued", started_at=now_utc(), message="待機中")
    db.add(job)
    db.commit()
    threading.Thread(target=run_library_import_background, args=(job.id, user.id, html), daemon=True).start()
    return RedirectResponse("/me?library=started", status_code=303)


@router.get("/me/library/status", response_class=HTMLResponse)
def me_library_status(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    return templates.TemplateResponse(
        request,
        "library_import_status.html",
        {
            "running_jobs": db.scalars(
                select(LibraryImportJob)
                .where(LibraryImportJob.user_id == user.id, LibraryImportJob.status.in_(["queued", "running"]))
                .order_by(LibraryImportJob.started_at.desc())
            ).all(),
            "recent_jobs": db.scalars(
                select(LibraryImportJob)
                .where(LibraryImportJob.user_id == user.id)
                .order_by(LibraryImportJob.started_at.desc())
                .limit(3)
            ).all(),
        },
    )


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
