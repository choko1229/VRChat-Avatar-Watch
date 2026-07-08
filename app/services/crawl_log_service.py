from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CrawlLog, now_utc


def mark_stale_running_logs(db: Session) -> int:
    logs = db.scalars(select(CrawlLog).where(CrawlLog.status.in_(["queued", "running"]))).all()
    for log in logs:
        log.status = "interrupted"
        log.message = "server restarted before crawl finished"
        log.finished_at = log.finished_at or now_utc()
    db.commit()
    return len(logs)
