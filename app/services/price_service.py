from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Item, PriceHistory, now_utc
from app.services.detection import detect_free, detect_sale


def record_price(db: Session, item: Item, new_price: int | None, has_booth_sale_label: bool = False) -> PriceHistory:
    item.previous_price = item.current_price
    item.current_price = new_price
    if new_price is not None:
        prices = [p for p in [item.lowest_price, item.highest_price, new_price] if p is not None]
        item.lowest_price = min(prices)
        item.highest_price = max(prices)
    item.is_free = detect_free(item.title, item.description, new_price)
    decision = detect_sale(new_price, item.previous_price, item.lowest_price, has_booth_sale_label)
    item.is_on_sale = decision.is_on_sale
    item.last_checked_at = now_utc()
    history = PriceHistory(item=item, price=new_price, is_free=item.is_free, is_on_sale=item.is_on_sale)
    db.add(history)
    return history
