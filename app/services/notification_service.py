from __future__ import annotations

import httpx
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Item,
    ItemAvatarRelation,
    Notification,
    NotificationSetting,
    Setting,
    User,
    UserAvatarWatch,
    UserFavorite,
    UserShopWatch,
    now_utc,
)


def _watched_user_ids_for_item(db: Session, item: Item) -> set[int]:
    conditions = [
        exists().where(UserFavorite.user_id == User.id, UserFavorite.item_id == item.id),
        exists()
        .where(UserAvatarWatch.user_id == User.id)
        .where(
            exists()
            .where(ItemAvatarRelation.item_id == item.id)
            .where(ItemAvatarRelation.avatar_id == UserAvatarWatch.avatar_id)
            .where(ItemAvatarRelation.match_type != "excluded")
        ),
    ]
    if item.shop_id:
        conditions.append(exists().where(UserShopWatch.user_id == User.id, UserShopWatch.shop_id == item.shop_id))
    return set(db.scalars(select(User.id).where(or_(*conditions))).all())


def _setting_allows(db: Session, user_id: int, notification_type: str, previous_price: int | None, current_price: int | None) -> bool:
    setting = db.scalar(select(NotificationSetting).where(NotificationSetting.user_id == user_id))
    if not setting:
        setting = NotificationSetting(user_id=user_id)
        db.add(setting)
        db.flush()
    if notification_type == "new":
        return setting.notify_new
    if notification_type == "free":
        return setting.notify_free
    if notification_type == "sale":
        if not setting.notify_sale:
            return False
        if setting.min_discount_rate and previous_price and current_price is not None and previous_price > 0:
            discount = int(((previous_price - current_price) / previous_price) * 100)
            return discount >= setting.min_discount_rate
        return True
    if notification_type == "price_change":
        return setting.notify_price_change
    return False


def create_item_notifications(
    db: Session,
    item: Item,
    *,
    is_new: bool,
    was_free: bool,
    was_on_sale: bool,
    previous_price: int | None,
) -> int:
    events: list[tuple[str, str]] = []
    if is_new:
        events.append(("new", "新着商品が追加されました"))
    if item.is_free and not was_free:
        events.append(("free", "無料化された商品があります"))
    if item.is_on_sale and not was_on_sale:
        events.append(("sale", "セール対象になった商品があります"))
    if previous_price is not None and item.current_price != previous_price:
        events.append(("price_change", "価格が変更された商品があります"))
    if not events:
        return 0

    created = 0
    for user_id in _watched_user_ids_for_item(db, item):
        for notification_type, title in events:
            if not _setting_allows(db, user_id, notification_type, previous_price, item.current_price):
                continue
            db.add(
                Notification(
                    user_id=user_id,
                    item_id=item.id,
                    notification_type=notification_type,
                    title=title,
                    message=item.title,
                )
            )
            created += 1
    return created


def _setting(db: Session, key: str) -> str | None:
    setting = db.scalar(select(Setting).where(Setting.key == key))
    return setting.value if setting else None


def dispatch_pending_notifications(db: Session, limit: int = 20) -> int:
    notifications = db.scalars(select(Notification).where(Notification.sent_at.is_(None)).order_by(Notification.created_at).limit(limit)).all()
    if not notifications:
        return 0
    discord_webhook = _setting(db, "discord_webhook_public")
    misskey_instance = (_setting(db, "misskey_instance_url") or "").rstrip("/")
    misskey_token = _setting(db, "misskey_token")
    if not discord_webhook and not (misskey_instance and misskey_token):
        return 0

    sent = 0
    with httpx.Client(timeout=15) as client:
        for notification in notifications:
            text = f"{notification.title}\n{notification.message or ''}"
            destinations: list[str] = []
            if discord_webhook:
                response = client.post(discord_webhook, json={"content": text})
                response.raise_for_status()
                destinations.append("discord")
            if misskey_instance and misskey_token:
                response = client.post(f"{misskey_instance}/api/notes/create", json={"i": misskey_token, "text": text})
                response.raise_for_status()
                destinations.append("misskey")
            notification.sent_to = ",".join(destinations)
            notification.sent_at = now_utc()
            sent += 1
    db.commit()
    return sent
