from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, quote_plus, urlencode, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawler.parser import ParsedItem, parse_item_detail, parse_search_results, summarize_parsed_items
from app.models import CrawlLog, CrawlTarget, ErrorLog, Item, ItemTag, Shop, now_utc
from app.services.avatar_service import ensure_avatar_page_for_item
from app.services.detection import apply_avatar_matches, detect_nsfw, detect_tool
from app.services.notification_service import create_item_notifications
from app.services.price_service import record_price

USER_AGENT = "VRChatAvatarWatch/0.1 (+public BOOTH metadata monitor; low frequency)"
BOOTH_BASE = "https://booth.pm"
ALLOWED_BOOTH_HOSTS = {"booth.pm", "www.booth.pm"}

# Admin-triggered crawls (background threads) and the scheduled worker each use
# their own DB session. Without serializing writes, overlapping crawls race on
# item/relation upserts and can deadlock or hit unique-constraint violations.
_crawl_write_lock = threading.Lock()


@dataclass
class CrawlResult:
    status: str
    item_count: int
    message: str
    status_code: int | None = None
    summary: dict | None = None


def ensure_utc_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def merge_parsed_item(base: ParsedItem, detail: ParsedItem) -> ParsedItem:
    return ParsedItem(
        booth_item_id=base.booth_item_id or detail.booth_item_id,
        title=detail.title or base.title,
        item_url=base.item_url or detail.item_url,
        image_url=detail.image_url or base.image_url,
        shop_name=detail.shop_name or base.shop_name,
        shop_url=detail.shop_url or base.shop_url,
        description=detail.description or base.description,
        price=detail.price if detail.price is not None else base.price,
        tags=list(dict.fromkeys([*base.tags, *detail.tags]))[:30],
        category=base.category or detail.category,
        has_sale_label=base.has_sale_label or detail.has_sale_label,
    )


def is_allowed_booth_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"}:
        return False
    hostname = (parsed.hostname or "").casefold()
    return hostname in ALLOWED_BOOTH_HOSTS or hostname.endswith(".booth.pm")


def search_page_url(url: str, page: int) -> str:
    if page <= 1:
        return url
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["page"] = str(page)
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def validate_crawl_target(target_type: str, target_value: str) -> str | None:
    value = target_value.strip()
    if not value:
        return "クロール対象が空です"
    if target_type not in {"keyword", "shop", "url"}:
        return "クロール種別が不正です"
    if target_type in {"shop", "url"} and not is_allowed_booth_url(value):
        return "BOOTHドメイン以外のURLはクロール対象にできません"
    return None


class BoothCrawler:
    def __init__(self, db: Session, create_client: bool = True):
        self.db = db
        self.client = httpx.AsyncClient(timeout=30, headers={"User-Agent": USER_AGENT, "Accept": "text/html"}) if create_client else None
        self.semaphore = asyncio.Semaphore(1)

    async def close(self) -> None:
        if self.client:
            try:
                await self.client.aclose()
            except RuntimeError as exc:
                if "closed" not in str(exc).lower():
                    raise

    async def robots_allows_url(self, url: str) -> bool:
        if not self.client:
            raise RuntimeError("crawler HTTP client is not initialized")
        try:
            response = await self.client.get(f"{BOOTH_BASE}/robots.txt")
            if response.status_code >= 500:
                return False
            parser = RobotFileParser()
            parser.set_url(f"{BOOTH_BASE}/robots.txt")
            parser.parse(response.text.splitlines())
            return parser.can_fetch(USER_AGENT, url)
        except httpx.HTTPError:
            return False

    async def fetch(self, url: str) -> httpx.Response:
        if not self.client:
            raise RuntimeError("crawler HTTP client is not initialized")
        if not is_allowed_booth_url(url):
            raise ValueError("only BOOTH public URLs can be fetched")
        async with self.semaphore:
            response = await self.client.get(url)
            if response.status_code in {403, 429} or response.status_code >= 500:
                await asyncio.sleep(5)
            return response

    def target_to_url(self, target: CrawlTarget) -> str:
        if target.target_type == "url":
            return target.target_value
        if target.target_type == "keyword":
            return f"{BOOTH_BASE}/ja/search/{quote_plus(target.target_value)}?tags%5B%5D=VRChat"
        if target.target_type == "shop":
            return target.target_value
        return target.target_value

    def min_crawl_interval_minutes(self) -> int:
        from app.models import Setting

        setting = self.db.scalar(select(Setting).where(Setting.key == "min_crawl_interval_minutes"))
        try:
            return max(0, int(setting.value if setting else "30"))
        except ValueError:
            return 30

    def detail_enrichment_limit(self) -> int:
        from app.models import Setting

        setting = self.db.scalar(select(Setting).where(Setting.key == "max_detail_pages_per_crawl"))
        try:
            return max(0, min(50, int(setting.value if setting else "20")))
        except ValueError:
            return 20

    def search_page_limit(self) -> int:
        from app.models import Setting

        setting = self.db.scalar(select(Setting).where(Setting.key == "max_search_pages_per_crawl"))
        try:
            return max(1, min(20, int(setting.value if setting else "5")))
        except ValueError:
            return 5

    def skip_reason_for_recent_target(self, target: CrawlTarget, force: bool = False) -> str | None:
        min_interval = self.min_crawl_interval_minutes()
        if target.last_crawled_at and not force and min_interval:
            next_allowed = ensure_utc_aware(target.last_crawled_at) + timedelta(minutes=min_interval)
            if now_utc() < next_allowed:
                return f"minimum crawl interval not elapsed ({min_interval} minutes)"
        return None

    async def crawl_target(self, target: CrawlTarget, force: bool = False, log: CrawlLog | None = None) -> CrawlResult:
        url = self.target_to_url(target)
        if log is None:
            log = CrawlLog(target_id=target.id, target_url=url, crawl_type=target.target_type, status="running", started_at=now_utc())
            self.db.add(log)
        else:
            log.target_id = target.id
            log.target_url = url
            log.crawl_type = target.target_type
            log.status = "running"
            log.started_at = log.started_at or now_utc()
            log.finished_at = None
            log.message = "crawl started"
        self.db.commit()
        started = time.perf_counter()
        with _crawl_write_lock:
            try:
                validation_error = validate_crawl_target(target.target_type, target.target_value)
                if validation_error:
                    raise ValueError(validation_error)
                skip_reason = self.skip_reason_for_recent_target(target, force)
                if skip_reason:
                    log.status = "skipped"
                    log.message = skip_reason
                    return CrawlResult("skipped", 0, log.message)
                if not await self.robots_allows_url(url):
                    raise RuntimeError("robots.txt does not allow this fetch or could not be confirmed")
                response = await self.fetch(url)
                if response.status_code in {403, 429} or response.status_code >= 500:
                    log.status = "deferred"
                    log.status_code = response.status_code
                    log.message = "BOOTH returned a throttling or server status; crawl stopped"
                    self.db.add(
                        ErrorLog(
                            source="booth_crawler",
                            level="warning",
                            message="BOOTH returned a throttling or server status",
                            detail=f"status_code={response.status_code} url={url}",
                        )
                    )
                    return CrawlResult("deferred", 0, log.message, response.status_code)
                response.raise_for_status()
                parsed_items = [parse_item_detail(response.text, url)] if target.target_type == "url" else await self.collect_search_items(url, response.text)
                count = self.upsert_items(parsed_items)
                target.last_crawled_at = now_utc()
                log.status = "success"
                log.status_code = response.status_code
                log.item_count = count
                log.message = "crawl completed"
                return CrawlResult("success", count, "crawl completed", response.status_code, summarize_parsed_items(parsed_items))
            except Exception as exc:
                self.db.rollback()
                log.status = "error"
                log.message = "crawl failed"
                log.error_detail = str(exc)[:2000]
                self.db.add(ErrorLog(source="booth_crawler", level="error", message="BOOTH取得に失敗しました", detail=str(exc)[:2000]))
                return CrawlResult("error", 0, "crawl failed")
            finally:
                log.finished_at = now_utc()
                log.duration_ms = int((time.perf_counter() - started) * 1000)
                self.db.commit()

    async def preview_target(self, target: CrawlTarget, force: bool = False) -> CrawlResult:
        url = self.target_to_url(target)
        validation_error = validate_crawl_target(target.target_type, target.target_value)
        if validation_error:
            return CrawlResult("error", 0, validation_error)
        skip_reason = self.skip_reason_for_recent_target(target, force)
        if skip_reason:
            return CrawlResult("skipped", 0, skip_reason)
        if not await self.robots_allows_url(url):
            return CrawlResult("error", 0, "robots.txt does not allow this fetch or could not be confirmed")
        response = await self.fetch(url)
        if response.status_code in {403, 429} or response.status_code >= 500:
            return CrawlResult("deferred", 0, "BOOTH returned a throttling or server status", response.status_code)
        response.raise_for_status()
        parsed_items = [parse_item_detail(response.text, url)] if target.target_type == "url" else await self.collect_search_items(url, response.text)
        return CrawlResult("preview", len(parsed_items), "preview completed; no items were saved", response.status_code, summarize_parsed_items(parsed_items))

    async def collect_search_items(self, first_url: str, first_html: str) -> list[ParsedItem]:
        items = parse_search_results(first_html, first_url)
        seen = {item.booth_item_id or item.item_url for item in items}
        for page in range(2, self.search_page_limit() + 1):
            page_url = search_page_url(first_url, page)
            try:
                if not await self.robots_allows_url(page_url):
                    break
                response = await self.fetch(page_url)
                if response.status_code in {403, 429} or response.status_code >= 500:
                    self.db.add(
                        ErrorLog(
                            source="booth_crawler",
                            level="warning",
                            message="BOOTH search page returned a throttling or server status",
                            detail=f"status_code={response.status_code} url={page_url}",
                        )
                    )
                    break
                response.raise_for_status()
                page_items = parse_search_results(response.text, page_url)
            except Exception as exc:
                self.db.add(
                    ErrorLog(
                        source="booth_crawler",
                        level="warning",
                        message="BOOTH search page fetch failed",
                        detail=f"url={page_url} error={str(exc)[:1500]}",
                    )
                )
                break
            new_items = []
            for item in page_items:
                key = item.booth_item_id or item.item_url
                if key not in seen:
                    seen.add(key)
                    new_items.append(item)
            if not new_items:
                break
            items.extend(new_items)
        return await self.enrich_parsed_items(items)

    def needs_detail_enrichment(self, item: ParsedItem) -> bool:
        return not item.description or not item.tags or item.price is None or not item.image_url or not item.shop_name

    async def enrich_parsed_items(self, parsed_items: list[ParsedItem]) -> list[ParsedItem]:
        limit = self.detail_enrichment_limit()
        if limit <= 0:
            return parsed_items
        enriched: list[ParsedItem] = []
        fetched = 0
        for item in parsed_items:
            if fetched >= limit or not self.needs_detail_enrichment(item):
                enriched.append(item)
                continue
            try:
                if not await self.robots_allows_url(item.item_url):
                    enriched.append(item)
                    continue
                response = await self.fetch(item.item_url)
                if response.status_code in {403, 429} or response.status_code >= 500:
                    self.db.add(
                        ErrorLog(
                            source="booth_crawler",
                            level="warning",
                            message="BOOTH detail page returned a throttling or server status",
                            detail=f"status_code={response.status_code} url={item.item_url}",
                        )
                    )
                    enriched.append(item)
                    continue
                response.raise_for_status()
                enriched.append(merge_parsed_item(item, parse_item_detail(response.text, item.item_url)))
                fetched += 1
            except Exception as exc:
                self.db.add(
                    ErrorLog(
                        source="booth_crawler",
                        level="warning",
                        message="BOOTH detail page enrichment failed",
                        detail=f"url={item.item_url} error={str(exc)[:1500]}",
                    )
                )
                enriched.append(item)
        return enriched

    def upsert_items(self, parsed_items: list[ParsedItem]) -> int:
        count = 0
        for parsed in parsed_items:
            if not parsed.item_url:
                continue
            is_new = False
            item = None
            if parsed.booth_item_id:
                item = self.db.scalar(select(Item).where(Item.booth_item_id == parsed.booth_item_id))
            if not item:
                item = self.db.scalar(select(Item).where(Item.item_url == parsed.item_url))
            if not item:
                item = Item(booth_item_id=parsed.booth_item_id, title=parsed.title, item_url=parsed.item_url)
                self.db.add(item)
                self.db.flush()
                is_new = True
            was_free = bool(item.is_free)
            was_on_sale = bool(item.is_on_sale)
            previous_price = item.current_price
            item.title = parsed.title
            item.description = parsed.description or item.description
            item.image_url = parsed.image_url or item.image_url
            item.shop_name = parsed.shop_name or item.shop_name
            item.shop_url = parsed.shop_url or item.shop_url
            if parsed.shop_name:
                shop = self.db.scalar(select(Shop).where(Shop.name == parsed.shop_name))
                if not shop:
                    shop = Shop(name=parsed.shop_name, shop_url=parsed.shop_url)
                    self.db.add(shop)
                    self.db.flush()
                elif parsed.shop_url:
                    shop.shop_url = parsed.shop_url
                item.shop_id = shop.id
            item.category = parsed.category or item.category
            item.is_nsfw = detect_nsfw(item.title, item.description, parsed.tags)
            item.is_tool = detect_tool(self.db, item.title, item.description, parsed.tags)
            item.last_checked_at = now_utc()
            for tag in parsed.tags:
                exists = self.db.scalar(select(ItemTag).where(ItemTag.item_id == item.id, ItemTag.tag == tag))
                if not exists:
                    self.db.add(ItemTag(item_id=item.id, tag=tag))
            record_price(self.db, item, parsed.price, parsed.has_sale_label)
            ensure_avatar_page_for_item(self.db, item, parsed.tags)
            apply_avatar_matches(self.db, item, parsed.tags)
            create_item_notifications(self.db, item, is_new=is_new, was_free=was_free, was_on_sale=was_on_sale, previous_price=previous_price)
            count += 1
        self.db.commit()
        return count
