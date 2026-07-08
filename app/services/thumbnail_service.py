from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import ROOT_DIR
from app.models import Item, ThumbnailCache, now_utc


def _cache_file(cache_path: str) -> Path:
    path = Path(cache_path)
    if path.is_absolute():
        return path
    return ROOT_DIR / cache_path.lstrip("/\\")


def prune_thumbnail_cache(db: Session, max_gb: int = 10) -> int:
    removed = 0
    now = now_utc()
    rows = db.scalars(select(ThumbnailCache).order_by(ThumbnailCache.created_at)).all()
    for row in list(rows):
        if row.expires_at <= now:
            _delete_thumbnail_row(db, row)
            removed += 1

    max_bytes = max(0, max_gb) * 1024 * 1024 * 1024
    rows = db.scalars(select(ThumbnailCache).order_by(ThumbnailCache.created_at)).all()
    total = sum(row.file_size or 0 for row in rows)
    for row in rows:
        if total <= max_bytes:
            break
        total -= row.file_size or 0
        _delete_thumbnail_row(db, row)
        removed += 1
    db.commit()
    return removed


def _delete_thumbnail_row(db: Session, row: ThumbnailCache) -> None:
    try:
        path = _cache_file(row.cache_path)
        if path.exists() and path.is_file():
            path.unlink()
    except OSError:
        pass
    db.query(Item).where(Item.thumbnail_cache_path == row.cache_path).update({Item.thumbnail_cache_path: None})
    db.delete(row)
