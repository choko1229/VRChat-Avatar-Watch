from __future__ import annotations

from sqlalchemy import Select, case

from app.models import Item

SORT_OPTIONS = ("new", "price_asc", "price_desc", "discount")
DEFAULT_SORT = "new"


def apply_sort(stmt: Select[tuple[Item]], sort: str | None) -> Select[tuple[Item]]:
    if sort not in SORT_OPTIONS:
        sort = DEFAULT_SORT
    stmt = stmt.order_by(None)
    if sort == "price_asc":
        return stmt.order_by(Item.current_price.is_(None), Item.current_price.asc(), Item.id.desc())
    if sort == "price_desc":
        return stmt.order_by(Item.current_price.is_(None), Item.current_price.desc(), Item.id.desc())
    if sort == "discount":
        discount_rate = case(
            (
                (Item.previous_price.is_not(None)) & (Item.previous_price > 0) & (Item.current_price.is_not(None)),
                (Item.previous_price - Item.current_price) * 1.0 / Item.previous_price,
            ),
            else_=None,
        )
        return stmt.order_by(discount_rate.is_(None), discount_rate.desc(), Item.id.desc())
    return stmt.order_by(Item.first_seen_at.desc(), Item.id.desc())
