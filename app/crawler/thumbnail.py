from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.config import ROOT_DIR
from app.models import ThumbnailCache, now_utc

CACHE_DIR = ROOT_DIR / "app" / "static" / "cache"


async def cache_thumbnail(db: Session, item_id: int, image_url: str, days: int = 30) -> str | None:
    if not image_url.startswith(("https://", "http://")):
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(image_url.split("?", 1)[0]).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        suffix = ".jpg"
    path = CACHE_DIR / f"item-{item_id}{suffix}"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.get(image_url)
            res.raise_for_status()
            path.write_bytes(res.content)
        rel_path = f"/static/cache/{path.name}"
        db.add(
            ThumbnailCache(
                item_id=item_id,
                original_url=image_url,
                cache_path=rel_path,
                file_size=path.stat().st_size,
                expires_at=now_utc() + timedelta(days=days),
            )
        )
        db.commit()
        return rel_path
    except Exception:
        return None
