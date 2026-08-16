from __future__ import annotations

import asyncio
import threading
import time

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.crawler.booth import CRAWL_WRITE_LOCK, BoothCrawler, validate_crawl_target
from app.crawler.parser import parse_item_detail, parse_search_results, summarize_parsed_items
from app.database import SessionLocal, get_db
from app.models import (
    Avatar,
    BaseBody,
    BaseBodyProposal,
    CrawlLog,
    CrawlTarget,
    ErrorLog,
    FacetTag,
    FacetTagSynonym,
    Item,
    ItemAvatarRelation,
    ItemFacetTag,
    Setting,
    Shop,
    Tool,
    User,
    now_utc,
)
from app.security import csrf_token, mask_secret, require_admin, verify_csrf
from app.services.admin_service import (
    apply_avatar_detail,
    create_manual_item,
    delete_item,
    delete_crawl_target,
    delete_avatar_and_redistribute,
    delete_shop,
    delete_tool,
    parse_tags,
    save_setting,
    save_tool,
    set_avatar_relation,
    update_manual_item,
)
from app.services.avatar_merge_service import find_duplicate_avatar_groups, merge_avatars
from app.services.avatar_service import find_low_confidence_avatars
from app.services.base_body_service import (
    apply_base_body_group,
    approve_proposal,
    detect_base_body_candidates,
    list_pending_proposals,
    reject_proposal,
    remove_avatar_from_base_body,
)
from app.services.detection import reclassify_all_items
from app.services.facet_service import all_facet_tags_grouped
from app.templating import templates

router = APIRouter(prefix="/admin")


async def run_crawl_target_async(crawler: BoothCrawler, target: CrawlTarget, force: bool, log: CrawlLog) -> None:
    try:
        await crawler.crawl_target(target, force=force, log=log)
    finally:
        await crawler.close()


async def refresh_avatar_from_booth(crawler: BoothCrawler, avatar: Avatar) -> None:
    if not avatar.booth_url:
        raise ValueError("BOOTH URL is not set")
    if not await crawler.robots_allows_url(avatar.booth_url):
        raise RuntimeError("robots.txt does not allow this fetch or could not be confirmed")
    response = await crawler.fetch(avatar.booth_url)
    if response.status_code in {403, 429} or response.status_code >= 500:
        raise RuntimeError(f"BOOTH returned status {response.status_code}")
    response.raise_for_status()
    apply_avatar_detail(crawler.db, avatar, parse_item_detail(response.text, avatar.booth_url))


def run_crawl_target_background(target_id: int, log_id: int, force: bool = False) -> None:
    db = SessionLocal()
    crawler = BoothCrawler(db)
    try:
        target = db.get(CrawlTarget, target_id)
        log = db.get(CrawlLog, log_id)
        if not log:
            return
        if not target or not target.is_active:
            log.status = "error"
            log.message = "crawl target is missing or inactive"
            log.finished_at = now_utc()
            db.add(ErrorLog(source="admin_crawl", level="error", message="crawl target is missing or inactive", detail=f"target_id={target_id}"))
            db.commit()
            return
        asyncio.run(run_crawl_target_async(crawler, target, force, log))
    except Exception as exc:
        db.rollback()
        log = db.get(CrawlLog, log_id)
        if log:
            log.status = "error"
            log.message = "crawl worker failed"
            log.error_detail = str(exc)[:2000]
            log.finished_at = now_utc()
        db.add(ErrorLog(source="admin_crawl", level="error", message="crawl worker failed", detail=str(exc)[:2000]))
        db.commit()
    finally:
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


@router.post("/items/{item_id}/delete")
def item_delete(request: Request, item_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_admin(request, db)
    verify_csrf(request, csrf)
    item = db.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="商品が見つかりません")
    delete_item(db, item)
    return RedirectResponse("/admin/items", status_code=303)


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


def run_reclassify_background(log_id: int) -> None:
    db = SessionLocal()
    try:
        log = db.get(CrawlLog, log_id)
        if log is None:
            return
        log.status = "running"
        log.message = "既存商品の再判定を開始しました"
        db.commit()
        started = time.perf_counter()
        with CRAWL_WRITE_LOCK:
            summary = reclassify_all_items(db, log)
        log.status = "success"
        log.item_count = summary["items"]
        log.message = (
            f"完了: {summary['items']:,}件処理・削除{summary['relations_removed']:,}件・"
            f"追加{summary['relations_added']:,}件・アバター{summary['avatars_touched']:,}件"
        )
        log.finished_at = now_utc()
        log.duration_ms = int((time.perf_counter() - started) * 1000)
        db.commit()
    except Exception as exc:
        db.rollback()
        log = db.get(CrawlLog, log_id)
        if log:
            log.status = "error"
            log.message = "再判定に失敗しました"
            log.error_detail = str(exc)[:2000]
            log.finished_at = now_utc()
        db.add(ErrorLog(source="admin_reclassify", level="error", message="既存商品の再判定に失敗しました", detail=str(exc)[:2000]))
        db.commit()
    finally:
        db.close()


@router.post("/avatars/reclassify")
def reclassify_avatars(request: Request, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_admin(request, db)
    verify_csrf(request, csrf)
    log = CrawlLog(
        target_url="internal:reclassify",
        crawl_type="reclassify",
        status="queued",
        started_at=now_utc(),
        message="再判定待機中",
    )
    db.add(log)
    db.commit()
    threading.Thread(target=run_reclassify_background, args=(log.id,), daemon=True).start()
    return RedirectResponse("/admin/avatars?reclassify=started", status_code=303)


@router.get("/avatars/reclassify/status", response_class=HTMLResponse)
def reclassify_status(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    return templates.TemplateResponse(
        request,
        "admin/reclassify_status.html",
        {
            "running_logs": db.scalars(
                select(CrawlLog)
                .where(CrawlLog.crawl_type == "reclassify", CrawlLog.status.in_(["queued", "running"]))
                .order_by(CrawlLog.started_at.desc())
            ).all(),
            "recent_logs": db.scalars(
                select(CrawlLog)
                .where(CrawlLog.crawl_type == "reclassify")
                .order_by(CrawlLog.started_at.desc())
                .limit(5)
            ).all(),
        },
    )


@router.get("/base-bodies", response_class=HTMLResponse)
def base_bodies_admin(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    return templates.TemplateResponse(
        request,
        "admin/base_bodies.html",
        {
            "user": user,
            "csrf_token": csrf_token(request),
            "candidates": detect_base_body_candidates(db),
            "base_bodies": db.scalars(select(BaseBody).order_by(BaseBody.name)).all(),
            "proposals": list_pending_proposals(db),
        },
    )


@router.get("/base-bodies/candidate-count", response_class=HTMLResponse)
def base_bodies_candidate_count(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    count = len(detect_base_body_candidates(db))
    return templates.TemplateResponse(request, "admin/_base_body_badge.html", {"count": count})


@router.post("/base-bodies/apply")
def base_bodies_apply(request: Request, csrf: str = Form(...), name: str = Form(...), avatar_ids: list[int] = Form(...), db: Session = Depends(get_db)):
    require_admin(request, db)
    verify_csrf(request, csrf)
    apply_base_body_group(db, name, avatar_ids)
    return RedirectResponse("/admin/base-bodies", status_code=303)


@router.post("/base-bodies/{base_body_id}/avatars/{avatar_id}/remove")
def base_bodies_remove_avatar(request: Request, base_body_id: int, avatar_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_admin(request, db)
    verify_csrf(request, csrf)
    avatar = db.get(Avatar, avatar_id)
    if avatar and avatar.base_body_id == base_body_id:
        remove_avatar_from_base_body(db, avatar)
    return RedirectResponse("/admin/base-bodies", status_code=303)


@router.post("/base-bodies/{base_body_id}/delete")
def base_bodies_delete(request: Request, base_body_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_admin(request, db)
    verify_csrf(request, csrf)
    base_body = db.get(BaseBody, base_body_id)
    if base_body:
        db.execute(update(Avatar).where(Avatar.base_body_id == base_body_id).values(base_body_id=None))
        db.delete(base_body)
        db.commit()
    return RedirectResponse("/admin/base-bodies", status_code=303)


@router.post("/base-bodies/proposals/{proposal_id}/approve")
def base_bodies_proposal_approve(request: Request, proposal_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_admin(request, db)
    verify_csrf(request, csrf)
    proposal = db.get(BaseBodyProposal, proposal_id)
    if proposal and proposal.status == "pending":
        approve_proposal(db, proposal)
    return RedirectResponse("/admin/base-bodies", status_code=303)


@router.post("/base-bodies/proposals/{proposal_id}/reject")
def base_bodies_proposal_reject(request: Request, proposal_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_admin(request, db)
    verify_csrf(request, csrf)
    proposal = db.get(BaseBodyProposal, proposal_id)
    if proposal and proposal.status == "pending":
        reject_proposal(db, proposal)
    return RedirectResponse("/admin/base-bodies", status_code=303)


@router.get("/facet-tags", response_class=HTMLResponse)
def facet_tags_admin(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    return templates.TemplateResponse(
        request,
        "admin/facet_tags.html",
        {
            "user": user,
            "csrf_token": csrf_token(request),
            "grouped_facet_tags": all_facet_tags_grouped(db),
        },
    )


@router.post("/facet-tags")
def facet_tags_create(
    request: Request,
    csrf: str = Form(...),
    facet_type: str = Form(...),
    slug: str = Form(...),
    label: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    verify_csrf(request, csrf)
    if not db.scalar(select(FacetTag).where(FacetTag.slug == slug)):
        db.add(FacetTag(facet_type=facet_type, slug=slug, label=label, description=description or None))
        db.commit()
    return RedirectResponse("/admin/facet-tags", status_code=303)


@router.post("/facet-tags/{facet_tag_id}/synonyms")
def facet_tags_add_synonym(
    request: Request,
    facet_tag_id: int,
    csrf: str = Form(...),
    keyword: str = Form(...),
    match_field: str = Form("tag"),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    verify_csrf(request, csrf)
    keyword = keyword.strip()
    if db.get(FacetTag, facet_tag_id) and keyword and match_field in {"tag", "title", "category"}:
        db.add(FacetTagSynonym(facet_tag_id=facet_tag_id, keyword=keyword, match_field=match_field))
        db.commit()
    return RedirectResponse("/admin/facet-tags", status_code=303)


@router.post("/facet-tags/{facet_tag_id}/delete")
def facet_tags_delete(request: Request, facet_tag_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_admin(request, db)
    verify_csrf(request, csrf)
    facet_tag = db.get(FacetTag, facet_tag_id)
    if facet_tag:
        db.execute(ItemFacetTag.__table__.delete().where(ItemFacetTag.facet_tag_id == facet_tag_id))
        db.delete(facet_tag)
        db.commit()
    return RedirectResponse("/admin/facet-tags", status_code=303)


@router.get("/avatars/cleanup", response_class=HTMLResponse)
def avatars_cleanup(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    return templates.TemplateResponse(
        request,
        "admin/avatars_cleanup.html",
        {
            "user": user,
            "csrf_token": csrf_token(request),
            "candidates": find_low_confidence_avatars(db),
        },
    )


@router.post("/avatars/cleanup/delete")
def avatars_cleanup_delete(request: Request, csrf: str = Form(...), avatar_ids: list[int] = Form(...), db: Session = Depends(get_db)):
    require_admin(request, db)
    verify_csrf(request, csrf)
    avatars = db.scalars(select(Avatar).where(Avatar.id.in_(avatar_ids))).all()
    for avatar in avatars:
        delete_avatar_and_redistribute(db, avatar)
    return RedirectResponse(f"/admin/avatars/cleanup?deleted={len(avatars)}", status_code=303)


@router.get("/avatars/duplicates", response_class=HTMLResponse)
def avatars_duplicates(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    return templates.TemplateResponse(
        request,
        "admin/avatars_duplicates.html",
        {
            "user": user,
            "csrf_token": csrf_token(request),
            "groups": find_duplicate_avatar_groups(db),
        },
    )


@router.post("/avatars/duplicates/merge")
def avatars_duplicates_merge(
    request: Request,
    csrf: str = Form(...),
    primary_id: int = Form(...),
    group_avatar_ids: list[int] = Form(...),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    verify_csrf(request, csrf)
    primary = db.get(Avatar, primary_id)
    if not primary:
        raise HTTPException(status_code=404, detail="アバターが見つかりません")
    duplicates = db.scalars(select(Avatar).where(Avatar.id.in_(group_avatar_ids), Avatar.id != primary_id)).all()
    merge_avatars(db, primary, duplicates)
    return RedirectResponse("/admin/avatars/duplicates", status_code=303)


# NOTE: this must stay registered after /avatars/reclassify above - FastAPI
# matches routes in registration order, and {avatar_id} would otherwise
# greedily match the literal "reclassify" path segment as a string and fail
# int conversion.
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


@router.post("/avatars/{avatar_id}/refresh")
def refresh_avatar(request: Request, avatar_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_admin(request, db)
    verify_csrf(request, csrf)
    avatar = db.get(Avatar, avatar_id)
    if not avatar:
        raise HTTPException(status_code=404, detail="アバターが見つかりません")
    crawler = BoothCrawler(db)
    try:
        asyncio.run(refresh_avatar_from_booth(crawler, avatar))
    except Exception as exc:
        db.rollback()
        db.add(
            ErrorLog(
                source="admin_avatar",
                level="warning",
                message="avatar refresh failed",
                detail=f"avatar_id={avatar_id} url={avatar.booth_url or ''} error={str(exc)[:1500]}",
            )
        )
        db.commit()
    finally:
        asyncio.run(crawler.close())
    return RedirectResponse("/admin/avatars", status_code=303)


@router.post("/avatars/{avatar_id}/delete")
def delete_avatar(request: Request, avatar_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_admin(request, db)
    verify_csrf(request, csrf)
    avatar = db.get(Avatar, avatar_id)
    if not avatar:
        raise HTTPException(status_code=404, detail="アバターが見つかりません")
    delete_avatar_and_redistribute(db, avatar)
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


@router.post("/tools/{tool_id}/delete")
def tool_delete(request: Request, tool_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_admin(request, db)
    verify_csrf(request, csrf)
    tool = db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="ツールが見つかりません")
    delete_tool(db, tool)
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


@router.post("/shops/{shop_id}/delete")
def shop_delete(request: Request, shop_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_admin(request, db)
    verify_csrf(request, csrf)
    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail="ショップが見つかりません")
    delete_shop(db, shop)
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
            "running_logs": db.scalars(select(CrawlLog).where(CrawlLog.status.in_(["queued", "running"])).order_by(CrawlLog.started_at.desc()).limit(10)).all(),
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
            "running_logs": db.scalars(select(CrawlLog).where(CrawlLog.status.in_(["queued", "running"])).order_by(CrawlLog.started_at.desc()).limit(10)).all(),
            "logs": db.scalars(select(CrawlLog).order_by(CrawlLog.started_at.desc()).limit(50)).all(),
        },
    )


@router.post("/crawl/run")
def crawl_run(
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
        queued_log = CrawlLog(
            target_id=target.id,
            target_url=BoothCrawler(db, create_client=False).target_to_url(target),
            crawl_type=target.target_type,
            status="queued",
            started_at=now_utc(),
            message="queued from admin",
        )
        db.add(queued_log)
        db.commit()
        threading.Thread(target=run_crawl_target_background, args=(target.id, queued_log.id, force == "on"), daemon=True).start()
    return RedirectResponse("/admin/crawl", status_code=303)


@router.post("/crawl/targets/{target_id}/delete")
def crawl_target_delete(request: Request, target_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_admin(request, db)
    verify_csrf(request, csrf)
    target = db.get(CrawlTarget, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="クロール対象が見つかりません")
    delete_crawl_target(db, target)
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
    crawl_request_interval_ms: str = Form("1000"),
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
    save_setting(db, "crawl_request_interval_ms", crawl_request_interval_ms)
    save_setting(db, "thumbnail_cache_max_gb", thumbnail_cache_max_gb)
    save_setting(db, "misskey_instance_url", misskey_instance_url)
    if misskey_token:
        save_setting(db, "misskey_token", misskey_token, True)
    if discord_webhook_admin:
        save_setting(db, "discord_webhook_admin", discord_webhook_admin, True)
    if discord_webhook_public:
        save_setting(db, "discord_webhook_public", discord_webhook_public, True)
    return RedirectResponse("/admin/settings", status_code=303)
