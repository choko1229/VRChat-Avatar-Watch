from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Item, ItemAvatarRelation
from app.services.sort_service import apply_sort


def latest_items(db: Session, limit: int = 12) -> list[Item]:
    return db.scalars(select(Item).options(selectinload(Item.tags), selectinload(Item.avatar_relations).selectinload(ItemAvatarRelation.avatar)).order_by(Item.first_seen_at.desc()).limit(limit)).unique().all()


def sale_items(db: Session, limit: int = 12, sort: str | None = None, offset: int = 0) -> list[Item]:
    stmt = select(Item).where(Item.is_on_sale.is_(True)).options(selectinload(Item.avatar_relations).selectinload(ItemAvatarRelation.avatar))
    stmt = apply_sort(stmt, sort) if sort else stmt.order_by(Item.updated_at.desc())
    return db.scalars(stmt.offset(offset).limit(limit)).unique().all()


def free_items(db: Session, limit: int = 12, sort: str | None = None, offset: int = 0) -> list[Item]:
    stmt = select(Item).where(Item.is_free.is_(True)).options(selectinload(Item.avatar_relations).selectinload(ItemAvatarRelation.avatar))
    stmt = apply_sort(stmt, sort) if sort else stmt.order_by(Item.updated_at.desc())
    return db.scalars(stmt.offset(offset).limit(limit)).unique().all()


def tool_items(db: Session, limit: int = 40, sort: str | None = None, offset: int = 0) -> list[Item]:
    stmt = select(Item).where(Item.is_tool.is_(True)).options(selectinload(Item.avatar_relations).selectinload(ItemAvatarRelation.avatar))
    stmt = apply_sort(stmt, sort) if sort else stmt.order_by(Item.updated_at.desc())
    return db.scalars(stmt.offset(offset).limit(limit)).unique().all()

