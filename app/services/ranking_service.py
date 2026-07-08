from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Item, RankingMetric, UserFavorite


def score_metric(metric: RankingMetric) -> float:
    return float(
        (metric.view_count or 0)
        + (metric.click_count or 0) * 2
        + (metric.favorite_count or 0) * 4
        + (metric.sale_view_count or 0) * 1.5
        + (metric.free_view_count or 0) * 1.5
    )


def sync_ranking_metrics(db: Session) -> int:
    favorite_counts = dict(db.execute(select(UserFavorite.item_id, func.count(UserFavorite.id)).group_by(UserFavorite.item_id)).all())
    metrics = db.scalars(select(RankingMetric)).all()
    for metric in metrics:
        metric.favorite_count = favorite_counts.get(metric.item_id, 0)
        metric.score = score_metric(metric)
    db.commit()
    return len(metrics)


def ranking_items(db: Session, limit: int = 12) -> list[Item]:
    sync_ranking_metrics(db)
    return db.scalars(
        select(Item)
        .join(RankingMetric, RankingMetric.item_id == Item.id)
        .where(RankingMetric.score > 0)
        .order_by(RankingMetric.score.desc(), RankingMetric.updated_at.desc())
        .limit(limit)
    ).all()
