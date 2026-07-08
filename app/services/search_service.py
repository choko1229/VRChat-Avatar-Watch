from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import Select, and_, exists, or_, select
from sqlalchemy.orm import Session

from app.models import Avatar, Item, ItemAvatarRelation, ItemTag


@dataclass
class SearchQuery:
    text_terms: list[str] = field(default_factory=list)
    exclude_terms: list[str] = field(default_factory=list)
    avatar: str | None = None
    shop: str | None = None
    tag: str | None = None
    free: bool | None = None
    sale: bool | None = None
    tool: bool | None = None
    nsfw: bool | None = None


def parse_bool(value: str) -> bool | None:
    value = value.casefold()
    if value in {"true", "1", "yes", "on"}:
        return True
    if value in {"false", "0", "no", "off"}:
        return False
    return None


def parse_search_query(raw: str | None) -> SearchQuery:
    query = SearchQuery()
    if not raw:
        return query
    for part in raw.split():
        if part.startswith("-") and len(part) > 1:
            query.exclude_terms.append(part[1:])
            continue
        if ":" in part:
            key, value = part.split(":", 1)
            key = key.casefold()
            if key == "avatar":
                query.avatar = value
            elif key == "shop":
                query.shop = value
            elif key == "tag":
                query.tag = value
            elif key == "free":
                query.free = parse_bool(value)
            elif key == "sale":
                query.sale = parse_bool(value)
            elif key == "tool":
                query.tool = parse_bool(value)
            elif key == "nsfw":
                query.nsfw = parse_bool(value)
            else:
                query.text_terms.append(part)
        else:
            query.text_terms.append(part)
    return query


def build_item_query(parsed: SearchQuery) -> Select[tuple[Item]]:
    stmt = select(Item).order_by(Item.first_seen_at.desc(), Item.id.desc())
    conditions = []
    for term in parsed.text_terms:
        like = f"%{term}%"
        conditions.append(or_(Item.title.ilike(like), Item.description.ilike(like), Item.shop_name.ilike(like)))
    for term in parsed.exclude_terms:
        like = f"%{term}%"
        conditions.append(and_(~Item.title.ilike(like), ~Item.description.ilike(like)))
    if parsed.shop:
        conditions.append(Item.shop_name.ilike(f"%{parsed.shop}%"))
    if parsed.free is not None:
        conditions.append(Item.is_free.is_(parsed.free))
    if parsed.sale is not None:
        conditions.append(Item.is_on_sale.is_(parsed.sale))
    if parsed.tool is not None:
        conditions.append(Item.is_tool.is_(parsed.tool))
    if parsed.nsfw is not None:
        conditions.append(Item.is_nsfw.is_(parsed.nsfw))
    if parsed.tag:
        conditions.append(exists().where(ItemTag.item_id == Item.id, ItemTag.tag.ilike(f"%{parsed.tag}%")))
    if parsed.avatar:
        conditions.append(
            exists()
            .where(ItemAvatarRelation.item_id == Item.id)
            .where(ItemAvatarRelation.match_type != "excluded")
            .where(
                exists()
                .where(Avatar.id == ItemAvatarRelation.avatar_id)
                .where(or_(Avatar.name.ilike(f"%{parsed.avatar}%"), Avatar.slug.ilike(f"%{parsed.avatar}%")))
            )
        )
    if conditions:
        stmt = stmt.where(and_(*conditions))
    return stmt


def search_items(db: Session, raw_query: str | None = None, limit: int = 40, offset: int = 0) -> list[Item]:
    parsed = parse_search_query(raw_query)
    return db.scalars(build_item_query(parsed).limit(limit).offset(offset)).unique().all()
