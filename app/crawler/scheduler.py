from __future__ import annotations

import asyncio

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.crawler.booth import BoothCrawler
from app.database import session_scope
from app.models import CrawlTarget, Setting


def _interval_hours() -> int:
    with session_scope() as db:
        setting = db.scalar(select(Setting).where(Setting.key == "crawl_interval_hours"))
        try:
            return max(1, int(setting.value if setting else "6"))
        except ValueError:
            return 6


async def crawl_active_targets_once() -> None:
    with session_scope() as db:
        targets = db.scalars(select(CrawlTarget).where(CrawlTarget.is_active.is_(True)).limit(20)).all()
        crawler = BoothCrawler(db)
        try:
            for target in targets:
                await crawler.crawl_target(target)
        finally:
            await crawler.close()


def run_crawl_job() -> None:
    asyncio.run(crawl_active_targets_once())


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Tokyo")
    scheduler.add_job(run_crawl_job, "interval", hours=_interval_hours(), id="booth_crawl", replace_existing=True)
    return scheduler
