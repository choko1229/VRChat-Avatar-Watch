from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ItemTag


def popular_tags(db: Session, limit: int = 20) -> list[tuple[str, int]]:
    # Surfaces the seller-authored BOOTH tags already collected in ItemTag as
    # a style/genre browsing entry point (girly, cool, japanese-style, etc.
    # commonly show up as seller tags) without needing a separate curated
    # taxonomy table and admin CRUD screen.
    rows = db.execute(
        select(ItemTag.tag, func.count(ItemTag.item_id).label("count"))
        .group_by(ItemTag.tag)
        .order_by(func.count(ItemTag.item_id).desc())
        .limit(limit)
    ).all()
    return [(tag, count) for tag, count in rows]
