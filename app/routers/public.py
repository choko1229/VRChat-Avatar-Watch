from __future__ import annotations

import asyncio
import threading
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.crawler.booth import BoothCrawler, title_looks_truncated
from app.crawler.parser import parse_item_detail
from app.database import SessionLocal, get_db
from app.models import Avatar, BaseBody, ErrorLog, Item, ItemAvatarRelation, PriceHistory, RankingMetric, User, now_utc
from app.security import csrf_token, current_user, require_user, verify_csrf
from app.services.avatar_service import featured_avatars
from app.services.base_body_service import list_base_bodies_with_counts
from app.services.item_service import free_items, latest_items, sale_items, tool_items
from app.services.push_service import has_subscription, vapid_public_key
from app.services.ranking_service import ranking_items
from app.services.request_service import requests_for_user, submit_crawl_request
from app.services.search_service import search_items
from app.services.seo_service import avatar_json_ld, base_body_json_ld, product_json_ld
from app.services.sort_service import DEFAULT_SORT, SORT_OPTIONS
from app.services.tag_service import popular_tags
from app.services.watch_service import (
    dashboard_for_user,
    is_avatar_watched,
    is_item_favorited,
    is_shop_watched,
    set_notification_setting,
    toggle_avatar_watch,
    toggle_item_favorite,
    toggle_shop_watch,
    watched_new_items,
)
from app.templating import canonical_url, templates

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
    user = current_user(request, db)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "watched_items": watched_new_items(db, user) if user else [],
            "featured_avatars": featured_avatars(db),
            "latest_items": latest_items(db),
            "sale_items": sale_items(db),
            "sale_count": db.scalar(select(func.count(Item.id)).where(Item.is_on_sale.is_(True))) or 0,
            "free_items": free_items(db),
            "free_count": db.scalar(select(func.count(Item.id)).where(Item.is_free.is_(True))) or 0,
            "quest_count": db.scalar(select(func.count(Item.id)).where(Item.is_quest_compatible.is_(True))) or 0,
            "tool_count": db.scalar(select(func.count(Item.id)).where(Item.is_tool.is_(True))) or 0,
            "ranking_items": ranking_items(db),
            "base_bodies": list_base_bodies_with_counts(db)[:6],
            "user": user,
        },
    )


PAGE_SIZE = 40


def _normalize_sort(sort: str | None) -> str:
    return sort if sort in SORT_OPTIONS else DEFAULT_SORT


def _split_page(items: list, page_size: int) -> tuple[list, bool]:
    # Fetch page_size + 1 upstream and look at whether that extra row showed
    # up, instead of a separate COUNT(*) query, to know if there's a next
    # page - one query instead of two, at the cost of discarding one row.
    has_more = len(items) > page_size
    return items[:page_size], has_more


def _grid_template(request: Request, full_template: str, offset: int) -> str:
    if not request.headers.get("HX-Request"):
        return full_template
    # offset==0 is the filter/sort bar re-rendering the whole grid; offset>0
    # is the infinite-scroll sentinel asking for just the next batch of cards.
    return "items/item_cards.html" if offset > 0 else "items/partial_grid.html"


@router.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = "", sort: str = DEFAULT_SORT, offset: int = 0, db: Session = Depends(get_db)):
    sort = _normalize_sort(sort)
    items, has_more = _split_page(search_items(db, q, sort, PAGE_SIZE + 1, offset), PAGE_SIZE)
    next_page_url = f"/search?q={quote(q)}&sort={sort}&offset={offset + PAGE_SIZE}" if has_more else None
    template = _grid_template(request, "search.html", offset)
    context = {
        "items": items,
        "q": q,
        "sort": sort,
        "next_page_url": next_page_url,
        "user": current_user(request, db),
        "meta_title": f"「{q}」の検索結果" if q else "商品検索",
        "meta_description": f"「{q}」のVRChat向けBooth検索結果です。" if q else "アバター対応商品・衣装・ギミック・ツールをキーワードやタグで検索できます。",
        "meta_canonical": canonical_url(request),
    }
    if template == "search.html":
        context["popular_tags"] = popular_tags(db)
    return templates.TemplateResponse(request, template, context)


@router.get("/sales", response_class=HTMLResponse)
def sales(request: Request, sort: str = DEFAULT_SORT, offset: int = 0, db: Session = Depends(get_db)):
    sort = _normalize_sort(sort)
    items, has_more = _split_page(sale_items(db, PAGE_SIZE + 1, sort, offset), PAGE_SIZE)
    next_page_url = f"/sales?sort={sort}&offset={offset + PAGE_SIZE}" if has_more else None
    template = _grid_template(request, "sales.html", offset)
    return templates.TemplateResponse(
        request,
        template,
        {
            "items": items,
            "sort": sort,
            "next_page_url": next_page_url,
            "user": current_user(request, db),
            "meta_title": "セール中の商品一覧",
            "meta_description": "VRChat向けBoothでセール中のアバター対応商品・衣装・ギミックをまとめて探せます。",
            "meta_canonical": f"{request.url.scheme}://{request.url.netloc}/sales",
        },
    )


@router.get("/free", response_class=HTMLResponse)
def free(request: Request, sort: str = DEFAULT_SORT, offset: int = 0, db: Session = Depends(get_db)):
    sort = _normalize_sort(sort)
    items, has_more = _split_page(free_items(db, PAGE_SIZE + 1, sort, offset), PAGE_SIZE)
    next_page_url = f"/free?sort={sort}&offset={offset + PAGE_SIZE}" if has_more else None
    template = _grid_template(request, "free.html", offset)
    return templates.TemplateResponse(
        request,
        template,
        {
            "items": items,
            "sort": sort,
            "next_page_url": next_page_url,
            "user": current_user(request, db),
            "meta_title": "無料配布の商品一覧",
            "meta_description": "VRChat向けBoothで無料配布中のアバター対応商品・衣装・ギミックをまとめて探せます。",
            "meta_canonical": f"{request.url.scheme}://{request.url.netloc}/free",
        },
    )


@router.get("/tools", response_class=HTMLResponse)
def tools(request: Request, sort: str = DEFAULT_SORT, offset: int = 0, db: Session = Depends(get_db)):
    sort = _normalize_sort(sort)
    items, has_more = _split_page(tool_items(db, PAGE_SIZE + 1, sort, offset), PAGE_SIZE)
    next_page_url = f"/tools?sort={sort}&offset={offset + PAGE_SIZE}" if has_more else None
    template = _grid_template(request, "tools.html", offset)
    return templates.TemplateResponse(
        request,
        template,
        {
            "items": items,
            "sort": sort,
            "next_page_url": next_page_url,
            "user": current_user(request, db),
            "meta_title": "ツール・ギミック一覧",
            "meta_description": "VRChat向けBoothのアバター改変ツール・ギミックをまとめて探せます。",
            "meta_canonical": f"{request.url.scheme}://{request.url.netloc}/tools",
        },
    )


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
        {
            "avatars": avatar_rows,
            "user": current_user(request, db),
            "meta_description": f"VRChatアバター{len(avatar_rows)}体の一覧です。各アバターの対応衣装・ギミック・関連商品を確認できます。",
        },
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
    related = db.scalars(
        select(Item)
        .where(Item.id != item.id)
        .options(selectinload(Item.avatar_relations).selectinload(ItemAvatarRelation.avatar))
        .limit(8)
    ).unique().all()
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
            "meta_title": item.title,
            "meta_description": item.description or f"{item.title} - VRChat向けBooth商品。{item.shop_name or ''}",
            "meta_image": item.thumbnail_cache_path or item.image_url,
            "meta_og_type": "product",
            "meta_json_ld": product_json_ld(request, item),
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
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request,
            "items/favorite_button.html",
            {"item": item, "csrf_token": csrf_token(request), "is_favorited": is_item_favorited(db, user, item)},
        )
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
        .options(selectinload(Item.avatar_relations).selectinload(ItemAvatarRelation.avatar))
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
    siblings = []
    if avatar.base_body_id:
        siblings = db.scalars(
            select(Avatar)
            .where(Avatar.base_body_id == avatar.base_body_id, Avatar.id != avatar.id)
            .order_by(Avatar.name)
        ).all()
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
            "sibling_avatars": siblings,
            "meta_title": f"{avatar.name}対応アイテム一覧",
            "meta_description": f"{avatar.name}に対応するVRChat向けBooth商品(衣装・ギミック・アクセサリーなど){len(items)}件をまとめて探せます。",
            "meta_image": avatar.image_url,
            "meta_json_ld": avatar_json_ld(request, avatar),
        },
    )


@router.get("/base-bodies", response_class=HTMLResponse)
def base_bodies_list(request: Request, db: Session = Depends(get_db)):
    base_bodies = list_base_bodies_with_counts(db)
    return templates.TemplateResponse(
        request,
        "base_bodies/list.html",
        {
            "base_bodies": base_bodies,
            "user": current_user(request, db),
            "meta_description": f"VRChatの共通素体(体型ブランド){len(base_bodies)}種の一覧です。素体ごとに対応アバターと商品をまとめて探せます。",
        },
    )


@router.get("/base-bodies/{slug}", response_class=HTMLResponse)
def base_body_detail(request: Request, slug: str, db: Session = Depends(get_db)):
    base_body = db.scalar(select(BaseBody).where(BaseBody.slug == slug))
    if not base_body:
        raise HTTPException(status_code=404, detail="素体が見つかりません")
    avatars = db.scalars(select(Avatar).where(Avatar.base_body_id == base_body.id).order_by(Avatar.name)).all()
    avatar_ids = [avatar.id for avatar in avatars]
    item_ids = db.scalars(
        select(ItemAvatarRelation.item_id)
        .where(ItemAvatarRelation.avatar_id.in_(avatar_ids), ItemAvatarRelation.match_type != "excluded")
        .distinct()
    ).all()
    items = db.scalars(
        select(Item)
        .where(Item.id.in_(item_ids))
        .options(selectinload(Item.avatar_relations).selectinload(ItemAvatarRelation.avatar))
        .order_by(Item.updated_at.desc())
    ).unique().all()
    return templates.TemplateResponse(
        request,
        "base_bodies/detail.html",
        {
            "base_body": base_body,
            "avatars": avatars,
            "items": items,
            "user": current_user(request, db),
            "meta_title": f"{base_body.name}対応アイテム一覧",
            "meta_description": f"共通素体「{base_body.name}」を使う{len(avatars)}体のアバターと、対応するVRChat向けBooth商品{len(items)}件をまとめて探せます。",
            "meta_json_ld": base_body_json_ld(request, base_body),
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
        data["push_subscribed"] = has_subscription(db, user)
        data["vapid_public_key"] = vapid_public_key(db)
    return templates.TemplateResponse(
        request, "me.html", {"user": user, "csrf_token": csrf_token(request), "meta_title": "マイページ", "meta_robots": "noindex, nofollow", **data}
    )


@router.get("/me/requests", response_class=HTMLResponse)
def me_requests(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    return templates.TemplateResponse(
        request,
        "me_requests_panel.html",
        {"my_requests": requests_for_user(db, user), "csrf_token": csrf_token(request)},
    )


@router.post("/me/requests", response_class=HTMLResponse)
def me_requests_submit(request: Request, csrf: str = Form(...), target_value: str = Form(...), db: Session = Depends(get_db)):
    user = require_user(request, db)
    verify_csrf(request, csrf)
    target, message = submit_crawl_request(db, user, target_value)
    return templates.TemplateResponse(
        request,
        "me_requests_panel.html",
        {
            "my_requests": requests_for_user(db, user),
            "csrf_token": csrf_token(request),
            "message": message,
            "success": target is not None,
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
