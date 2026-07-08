from __future__ import annotations

import asyncio
import threading
import time

from sqlalchemy import select

from app.crawler.booth import BoothCrawler
from app.database import SessionLocal
from app.models import CrawlTarget, ErrorLog, Setting
from app.services.notification_service import dispatch_pending_notifications
from app.services.ranking_service import sync_ranking_metrics
from app.services.thumbnail_service import prune_thumbnail_cache

_scheduler_started = False
_scheduler_lock = threading.Lock()


def setting_int(db, key: str, default: int) -> int:
    setting = db.scalar(select(Setting).where(Setting.key == key))
    try:
        return int(setting.value if setting and setting.value is not None else default)
    except ValueError:
        return default


async def _crawl_active_targets(db) -> None:
    targets = db.scalars(select(CrawlTarget).where(CrawlTarget.is_active.is_(True)).order_by(CrawlTarget.id)).all()
    crawler = BoothCrawler(db)
    try:
        for target in targets:
            await crawler.crawl_target(target)
    finally:
        await crawler.close()


def run_maintenance_once() -> None:
    db = SessionLocal()
    try:
        asyncio.run(_crawl_active_targets(db))
        prune_thumbnail_cache(db, setting_int(db, "thumbnail_cache_max_gb", 10))
        sync_ranking_metrics(db)
        dispatch_pending_notifications(db)
    except Exception as exc:
        db.rollback()
        db.add(ErrorLog(source="scheduler", level="error", message="scheduled maintenance failed", detail=str(exc)[:2000]))
        db.commit()
    finally:
        db.close()


def _worker() -> None:
    while True:
        db = SessionLocal()
        try:
            interval_hours = max(1, setting_int(db, "crawl_interval_hours", 6))
        finally:
            db.close()
        time.sleep(interval_hours * 60 * 60)
        run_maintenance_once()


def start_scheduler() -> bool:
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return False
        _scheduler_started = True
        threading.Thread(target=_worker, name="vrc-aw-scheduler", daemon=True).start()
        return True
