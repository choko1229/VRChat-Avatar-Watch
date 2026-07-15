from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import parse_qsl, quote_plus, urlencode, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawler.parser import ParsedItem, parse_item_detail, parse_search_results, summarize_parsed_items
from app.models import CrawlLog, CrawlTarget, ErrorLog, Item, ItemTag, Shop, ensure_utc_aware, now_utc
from app.services.avatar_service import ensure_avatar_page_for_item
from app.services.detection import apply_avatar_matches, detect_nsfw, detect_tool
from app.services.notification_service import create_item_notifications
from app.services.price_service import record_price

USER_AGENT = "VRChatAvatarWatch/0.1 (+public BOOTH metadata monitor; low frequency)"
BOOTH_BASE = "https://booth.pm"
ALLOWED_BOOTH_HOSTS = {"booth.pm", "www.booth.pm"}

# Admins can raise "検索取得ページ数" in /admin/settings, but we still cap it so a
# typo (or an overly broad keyword) can't turn one crawl into an unbounded
# number of requests against BOOTH. Keep this in sync with the help text in
# admin/settings.html.
MAX_SEARCH_PAGES_PER_CRAWL = 500

# Admin-triggered crawls (background threads) and the scheduled worker each use
# their own DB session. Without serializing writes, overlapping crawls race on
# item/relation upserts and can deadlock or hit unique-constraint violations.
# Also held by the bulk avatar-reclassification job (app.routers.admin), since
# that touches the same Item/Avatar/ItemAvatarRelation rows.
CRAWL_WRITE_LOCK = threading.Lock()


@dataclass
class CrawlResult:
    status: str
    item_count: int
    message: str
    status_code: int | None = None
    summary: dict | None = None


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


def title_looks_truncated(title: str | None) -> bool:
    # BOOTH's search-result cards truncate long titles server-side and mark
    # the cut with an ellipsis. A truncated title can hide the very part of
    # the name that would have matched an avatar, so treat it the same as a
    # missing field and always fetch the (untruncated) detail page for it.
    if not title:
        return False
    return title.rstrip().endswith(("…", "..."))


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
        # robots.txt doesn't change mid-crawl, but robots_allows_url() used to be
        # called once per page/detail fetch, silently doubling the request count
        # against BOOTH on multi-page crawls. Fetch it once per crawler instance.
        self._robots_parser: RobotFileParser | None = None
        self._robots_fetch_failed = False
        # Tracks detail-page fetches used so far in the current crawl so the
        # max_detail_pages_per_crawl budget is respected across pages, since
        # enrichment now happens per search-results page instead of once for
        # the whole crawl at the end.
        self._detail_enrichment_used = 0

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
        if self._robots_parser is None and not self._robots_fetch_failed:
            try:
                response = await self.client.get(f"{BOOTH_BASE}/robots.txt")
                if response.status_code >= 500:
                    self._robots_fetch_failed = True
                else:
                    parser = RobotFileParser()
                    parser.set_url(f"{BOOTH_BASE}/robots.txt")
                    parser.parse(response.text.splitlines())
                    self._robots_parser = parser
            except httpx.HTTPError:
                self._robots_fetch_failed = True
        if self._robots_parser is None:
            return False
        return self._robots_parser.can_fetch(USER_AGENT, url)

    def request_interval_ms(self) -> int:
        from app.models import Setting

        setting = self.db.scalar(select(Setting).where(Setting.key == "crawl_request_interval_ms"))
        try:
            return max(0, min(60000, int(setting.value if setting else "1000")))
        except ValueError:
            return 1000

    async def pace(self) -> None:
        # Called between successive page/detail fetches within a single crawl
        # to spread requests out and make hitting BOOTH's rate limiting less
        # likely. Not applied to one-off fetches (robots.txt, a single item).
        interval_ms = self.request_interval_ms()
        if interval_ms > 0:
            await asyncio.sleep(interval_ms / 1000)

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
            return max(1, min(MAX_SEARCH_PAGES_PER_CRAWL, int(setting.value if setting else "5")))
        except ValueError:
            return 5

    def skip_reason_for_recent_target(self, target: CrawlTarget, force: bool = False) -> str | None:
        min_interval = self.min_crawl_interval_minutes()
        if target.last_crawled_at and not force and min_interval:
            next_allowed = ensure_utc_aware(target.last_crawled_at) + timedelta(minutes=min_interval)
            if now_utc() < next_allowed:
                return f"minimum crawl interval not elapsed ({min_interval} minutes)"
        return None

    def report_progress(self, log: CrawlLog | None, message: str, item_count: int | None = None) -> None:
        # Lets the "実行中" admin panel show what a running crawl is actually
        # doing instead of a static "crawl started" until it finishes. Commits
        # immediately so the htmx poll (every 2s) picks it up right away.
        if log is None:
            return
        log.message = message
        if item_count is not None:
            log.item_count = item_count
        self.db.commit()

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
        with CRAWL_WRITE_LOCK:
            try:
                validation_error = validate_crawl_target(target.target_type, target.target_value)
                if validation_error:
                    raise ValueError(validation_error)
                skip_reason = self.skip_reason_for_recent_target(target, force)
                if skip_reason:
                    log.status = "skipped"
                    log.message = skip_reason
                    return CrawlResult("skipped", 0, log.message)
                self.report_progress(log, "robots.txtを確認中")
                if not await self.robots_allows_url(url):
                    raise RuntimeError("robots.txt does not allow this fetch or could not be confirmed")
                self.report_progress(log, "ページを取得中")
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
                if target.target_type == "url":
                    parsed_items = [parse_item_detail(response.text, url)]
                    self.report_progress(log, f"{len(parsed_items)}件をDBに保存中", len(parsed_items))
                    count = self.upsert_items(parsed_items)
                else:
                    # Saves each search-results page to the DB as soon as it's
                    # fetched and enriched, rather than holding everything in
                    # memory until the whole crawl finishes.
                    parsed_items, count = await self.collect_search_items(url, response.text, log, persist=True)
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
        if target.target_type == "url":
            parsed_items = [parse_item_detail(response.text, url)]
        else:
            parsed_items, _ = await self.collect_search_items(url, response.text)
        return CrawlResult("preview", len(parsed_items), "preview completed; no items were saved", response.status_code, summarize_parsed_items(parsed_items))

    async def collect_search_items(
        self, first_url: str, first_html: str, log: CrawlLog | None = None, persist: bool = False
    ) -> tuple[list[ParsedItem], int]:
        self._detail_enrichment_used = 0
        seen: set[str] = set()
        all_items: list[ParsedItem] = []
        saved_count = 0

        async def process_batch(batch: list[ParsedItem]) -> None:
            nonlocal saved_count
            if not batch:
                return
            enriched_batch = await self.enrich_parsed_items(batch, log)
            all_items.extend(enriched_batch)
            if persist:
                saved_count += self.upsert_items(enriched_batch)

        page_limit = self.search_page_limit()
        first_page_items = parse_search_results(first_html, first_url)
        for item in first_page_items:
            seen.add(item.booth_item_id or item.item_url)
        self.report_progress(log, f"検索結果 1/{page_limit} ページを取得中", len(first_page_items))
        await process_batch(first_page_items)
        if persist:
            self.report_progress(log, f"検索結果 1/{page_limit} ページを保存済み({saved_count}件)", saved_count)

        for page in range(2, page_limit + 1):
            page_url = search_page_url(first_url, page)
            try:
                if not await self.robots_allows_url(page_url):
                    break
                self.report_progress(log, f"検索結果 {page}/{page_limit} ページを取得中", len(all_items))
                await self.pace()
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
            await process_batch(new_items)
            if persist:
                self.report_progress(log, f"検索結果 {page}/{page_limit} ページを保存済み({saved_count}件)", saved_count)
        return all_items, saved_count

    def needs_detail_enrichment(self, item: ParsedItem) -> bool:
        return (
            not item.description
            or not item.tags
            or item.price is None
            or not item.image_url
            or not item.shop_name
            or title_looks_truncated(item.title)
        )

    async def enrich_parsed_items(self, parsed_items: list[ParsedItem], log: CrawlLog | None = None) -> list[ParsedItem]:
        limit = self.detail_enrichment_limit()
        remaining = max(0, limit - self._detail_enrichment_used)
        if remaining <= 0:
            return parsed_items
        total = min(remaining, sum(1 for item in parsed_items if self.needs_detail_enrichment(item)))
        enriched: list[ParsedItem] = []
        fetched = 0
        for item in parsed_items:
            if fetched >= remaining or not self.needs_detail_enrichment(item):
                enriched.append(item)
                continue
            try:
                if not await self.robots_allows_url(item.item_url):
                    enriched.append(item)
                    continue
                if total:
                    self.report_progress(log, f"商品詳細 {self._detail_enrichment_used + fetched + 1}/{self._detail_enrichment_used + total} 件を取得中", len(parsed_items))
                await self.pace()
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
        self._detail_enrichment_used += fetched
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
