from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Avatar,
    Item,
    Notification,
    NotificationSetting,
    Shop,
    User,
    UserAvatarWatch,
    UserFavorite,
    UserShopWatch,
)


def notification_setting_for_user(db: Session, user: User) -> NotificationSetting:
    setting = db.scalar(select(NotificationSetting).where(NotificationSetting.user_id == user.id))
    if not setting:
        setting = NotificationSetting(user_id=user.id)
        db.add(setting)
        db.flush()
    return setting


def set_notification_setting(
    db: Session,
    user: User,
    *,
    notify_sale: bool,
    notify_free: bool,
    notify_new: bool,
    notify_price_change: bool,
    min_discount_rate: int,
    nsfw_enabled: bool,
) -> NotificationSetting:
    setting = notification_setting_for_user(db, user)
    setting.notify_sale = notify_sale
    setting.notify_free = notify_free
    setting.notify_new = notify_new
    setting.notify_price_change = notify_price_change
    setting.min_discount_rate = max(0, min(100, min_discount_rate))
    user.nsfw_enabled = nsfw_enabled
    db.commit()
    return setting


def toggle_item_favorite(db: Session, user: User, item: Item) -> bool:
    favorite = db.scalar(select(UserFavorite).where(UserFavorite.user_id == user.id, UserFavorite.item_id == item.id))
    if favorite:
        db.delete(favorite)
        db.commit()
        return False
    db.add(UserFavorite(user_id=user.id, item_id=item.id))
    db.commit()
    return True


def toggle_avatar_watch(db: Session, user: User, avatar: Avatar) -> bool:
    watch = db.scalar(select(UserAvatarWatch).where(UserAvatarWatch.user_id == user.id, UserAvatarWatch.avatar_id == avatar.id))
    if watch:
        db.delete(watch)
        db.commit()
        return False
    db.add(UserAvatarWatch(user_id=user.id, avatar_id=avatar.id))
    db.commit()
    return True


def toggle_shop_watch(db: Session, user: User, shop: Shop) -> bool:
    watch = db.scalar(select(UserShopWatch).where(UserShopWatch.user_id == user.id, UserShopWatch.shop_id == shop.id))
    if watch:
        db.delete(watch)
        db.commit()
        return False
    db.add(UserShopWatch(user_id=user.id, shop_id=shop.id))
    db.commit()
    return True


def is_item_favorited(db: Session, user: User | None, item: Item) -> bool:
    return bool(user and db.scalar(select(UserFavorite).where(UserFavorite.user_id == user.id, UserFavorite.item_id == item.id)))


def is_avatar_watched(db: Session, user: User | None, avatar: Avatar) -> bool:
    return bool(user and db.scalar(select(UserAvatarWatch).where(UserAvatarWatch.user_id == user.id, UserAvatarWatch.avatar_id == avatar.id)))


def is_shop_watched(db: Session, user: User | None, shop: Shop | None) -> bool:
    return bool(user and shop and db.scalar(select(UserShopWatch).where(UserShopWatch.user_id == user.id, UserShopWatch.shop_id == shop.id)))


def dashboard_for_user(db: Session, user: User) -> dict:
    setting = notification_setting_for_user(db, user)
    favorite_items = db.scalars(
        select(Item).join(UserFavorite, UserFavorite.item_id == Item.id).where(UserFavorite.user_id == user.id).order_by(UserFavorite.created_at.desc())
    ).all()
    watched_avatars = db.scalars(
        select(Avatar).join(UserAvatarWatch, UserAvatarWatch.avatar_id == Avatar.id).where(UserAvatarWatch.user_id == user.id).order_by(UserAvatarWatch.created_at.desc())
    ).all()
    watched_shops = db.scalars(
        select(Shop).join(UserShopWatch, UserShopWatch.shop_id == Shop.id).where(UserShopWatch.user_id == user.id).order_by(UserShopWatch.created_at.desc())
    ).all()
    notifications = db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(50)).all()
    return {
        "setting": setting,
        "favorite_items": favorite_items,
        "watched_avatars": watched_avatars,
        "watched_shops": watched_shops,
        "notifications": notifications,
    }
