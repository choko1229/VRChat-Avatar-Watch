from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import func, select

from app.crawler.booth import BoothCrawler
from app.database import SessionLocal
from app.models import CrawlLog, CrawlTarget, ErrorLog, Item, PriceHistory


def target_for_keyword(db, keyword: str) -> CrawlTarget:
    target = db.scalar(
        select(CrawlTarget).where(CrawlTarget.target_type == "keyword", CrawlTarget.target_value == keyword)
    )
    if not target:
        target = CrawlTarget(target_type="keyword", target_value=keyword)
        db.add(target)
        db.commit()
        db.refresh(target)
    return target


async def run_check(keyword: str, save: bool) -> int:
    db = SessionLocal()
    crawler = BoothCrawler(db)
    try:
        target = target_for_keyword(db, keyword)
        preview = await crawler.preview_target(target, force=True)
        print(f"preview status={preview.status} code={preview.status_code} items={preview.item_count} summary={preview.summary}")
        if preview.status not in {"preview", "deferred"}:
            return 1

        if save:
            first = await crawler.crawl_target(target, force=True)
            print(f"save status={first.status} code={first.status_code} items={first.item_count} summary={first.summary}")
            second = await crawler.crawl_target(target, force=False)
            print(f"second status={second.status} code={second.status_code} items={second.item_count} message={second.message}")

        item_count = db.scalar(select(func.count()).select_from(Item))
        price_count = db.scalar(select(func.count()).select_from(PriceHistory))
        crawl_log_count = db.scalar(select(func.count()).select_from(CrawlLog))
        error_log_count = db.scalar(select(func.count()).select_from(ErrorLog))
        latest_log = db.scalar(select(CrawlLog).order_by(CrawlLog.started_at.desc()))
        print(
            "db "
            f"items={item_count} price_histories={price_count} "
            f"crawl_logs={crawl_log_count} error_logs={error_log_count}"
        )
        if latest_log:
            print(
                "latest_log "
                f"status={latest_log.status} code={latest_log.status_code} "
                f"items={latest_log.item_count} message={latest_log.message}"
            )
        return 0
    finally:
        await crawler.close()
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a low-frequency BOOTH production crawl check.")
    parser.add_argument("--keyword", default="キプフェル")
    parser.add_argument("--save", action="store_true", help="Actually save one crawl, then verify skip on immediate retry.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run_check(args.keyword, args.save)))


if __name__ == "__main__":
    main()
