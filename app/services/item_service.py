from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Item


def latest_items(db: Session, limit: int = 12) -> list[Item]:
    return db.scalars(select(Item).options(selectinload(Item.tags), selectinload(Item.avatar_relations)).order_by(Item.first_seen_at.desc()).limit(limit)).unique().all()


def sale_items(db: Session, limit: int = 12) -> list[Item]:
    return db.scalars(select(Item).where(Item.is_on_sale.is_(True)).order_by(Item.updated_at.desc()).limit(limit)).all()


def free_items(db: Session, limit: int = 12) -> list[Item]:
    return db.scalars(select(Item).where(Item.is_free.is_(True)).order_by(Item.updated_at.desc()).limit(limit)).all()


def tool_items(db: Session, limit: int = 40) -> list[Item]:
    return db.scalars(select(Item).where(Item.is_tool.is_(True)).order_by(Item.updated_at.desc()).limit(limit)).all()
