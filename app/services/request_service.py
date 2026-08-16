from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawler.booth import BoothCrawler, is_allowed_booth_url, validate_crawl_target
from app.models import CrawlTarget, User

_STATUS_MESSAGES = {
    "error": "取得に失敗しました。URLやキーワードを確認してください",
    "deferred": "BOOTHから一時的に取得できませんでした。しばらくしてから再度お試しください",
    "skipped": "直近に確認済みのため、今は追加できません",
}


def target_type_for_value(value: str) -> str:
    return "url" if is_allowed_booth_url(value) else "keyword"


def requests_for_user(db: Session, user: User) -> list[CrawlTarget]:
    return db.scalars(
        select(CrawlTarget).where(CrawlTarget.submitted_by_user_id == user.id).order_by(CrawlTarget.created_at.desc())
    ).all()


def submit_crawl_request(db: Session, user: User, target_value: str) -> tuple[CrawlTarget | None, str]:
    # No human review queue: we try the crawl immediately against a
    # not-yet-persisted CrawlTarget (or a matching inactive one), so nothing
    # new is written unless it actually turns up items. A bad submission
    # never sits around waiting on an admin to reject it.
    target_value = target_value.strip()
    target_type = target_type_for_value(target_value)
    validation_error = validate_crawl_target(target_type, target_value)
    if validation_error:
        return None, validation_error

    existing = db.scalar(
        select(CrawlTarget).where(CrawlTarget.target_type == target_type, CrawlTarget.target_value == target_value)
    )
    if existing and existing.is_active:
        return None, "このアバター/ショップ/商品はすでに登録されています"

    trial_target = existing or CrawlTarget(target_type=target_type, target_value=target_value)
    crawler = BoothCrawler(db)
    try:
        result = asyncio.run(crawler.crawl_target(trial_target, force=True))
    finally:
        asyncio.run(crawler.close())

    if result.status == "success" and result.item_count > 0:
        if existing:
            existing.is_active = True
            existing.submitted_by_user_id = user.id
            target = existing
        else:
            target = CrawlTarget(
                target_type=target_type,
                target_value=target_value,
                is_active=True,
                submitted_by_user_id=user.id,
            )
            db.add(target)
        db.commit()
        return target, f"登録しました({result.item_count:,}件を取得しました)"

    db.rollback()
    return None, _STATUS_MESSAGES.get(result.status, "対象の商品が見つかりませんでした")
