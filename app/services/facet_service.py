from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import FacetTag, FacetTagSynonym, Item, ItemFacetTag


@dataclass
class FacetIndex:
    # Bundles every FacetTag's synonyms for reuse across a whole crawl/
    # reclassify batch, same pattern as AvatarMatchIndex in detection.py -
    # avoids re-querying every synonym for every single item.
    entries: list[tuple[FacetTag, str, str]]  # (facet_tag, keyword_casefold, match_field)

    @classmethod
    def build(cls, db: Session) -> "FacetIndex":
        synonyms = db.scalars(select(FacetTagSynonym).options(selectinload(FacetTagSynonym.facet_tag))).all()
        entries = [(s.facet_tag, s.keyword.casefold(), s.match_field) for s in synonyms if s.keyword.strip()]
        return cls(entries=entries)


def apply_facet_tags(db: Session, item: Item, tags: list[str] | None, index: FacetIndex) -> None:
    haystacks = {
        "tag": " / ".join(tags or []).casefold(),
        "title": (item.title or "").casefold(),
        "category": (item.category or "").casefold(),
    }
    matched_ids: set[int] = set()
    for facet_tag, keyword, match_field in index.entries:
        if facet_tag.id in matched_ids:
            continue
        haystack = haystacks.get(match_field, haystacks["tag"])
        if keyword and keyword in haystack:
            exists = db.scalar(
                select(ItemFacetTag).where(ItemFacetTag.item_id == item.id, ItemFacetTag.facet_tag_id == facet_tag.id)
            )
            if not exists:
                db.add(ItemFacetTag(item_id=item.id, facet_tag_id=facet_tag.id))
            matched_ids.add(facet_tag.id)


def facet_tags_by_type(db: Session, facet_type: str) -> list[FacetTag]:
    return db.scalars(select(FacetTag).where(FacetTag.facet_type == facet_type).order_by(FacetTag.label)).all()


def all_facet_tags_grouped(db: Session) -> dict[str, list[FacetTag]]:
    grouped: dict[str, list[FacetTag]] = {}
    for facet_tag in db.scalars(select(FacetTag).order_by(FacetTag.facet_type, FacetTag.label)).all():
        grouped.setdefault(facet_tag.facet_type, []).append(facet_tag)
    return grouped


def popular_facet_tags(db: Session, facet_type: str | None = None, limit: int = 20) -> list[tuple[FacetTag, int]]:
    stmt = (
        select(FacetTag, func.count(ItemFacetTag.id))
        .join(ItemFacetTag, ItemFacetTag.facet_tag_id == FacetTag.id)
        .group_by(FacetTag.id)
        .order_by(func.count(ItemFacetTag.id).desc())
        .limit(limit)
    )
    if facet_type:
        stmt = stmt.where(FacetTag.facet_type == facet_type)
    return db.execute(stmt).all()


def items_for_facet_tag(db: Session, facet_tag: FacetTag):
    return (
        select(Item)
        .join(ItemFacetTag, ItemFacetTag.item_id == Item.id)
        .where(ItemFacetTag.facet_tag_id == facet_tag.id)
        .order_by(Item.updated_at.desc())
    )
