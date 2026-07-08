from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class Setting(Base, TimestampMixin):
    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(191), unique=True, index=True)
    value: Mapped[str | None] = mapped_column(Text)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    discord_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(191))
    display_name: Mapped[str | None] = mapped_column(String(191))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    nsfw_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    theme_mode: Mapped[str] = mapped_column(String(20), default="system")
    admin: Mapped["AdminUser | None"] = relationship(back_populates="user")


class AdminUser(Base):
    __tablename__ = "admin_users"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    discord_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    user: Mapped[User | None] = relationship(back_populates="admin")


class Avatar(Base, TimestampMixin):
    __tablename__ = "avatars"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(191), unique=True)
    slug: Mapped[str] = mapped_column(String(191), unique=True, index=True)
    reading: Mapped[str | None] = mapped_column(String(191))
    english_name: Mapped[str | None] = mapped_column(String(191))
    booth_url: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    search_keywords: Mapped[str | None] = mapped_column(Text)
    exclude_keywords: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    aliases: Mapped[list["AvatarAlias"]] = relationship(back_populates="avatar", cascade="all, delete-orphan")


class AvatarAlias(Base):
    __tablename__ = "avatar_aliases"
    id: Mapped[int] = mapped_column(primary_key=True)
    avatar_id: Mapped[int] = mapped_column(ForeignKey("avatars.id"))
    alias: Mapped[str] = mapped_column(String(191), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    avatar: Mapped[Avatar] = relationship(back_populates="aliases")
    __table_args__ = (UniqueConstraint("avatar_id", "alias", name="uq_avatar_alias"),)


class Tool(Base, TimestampMixin):
    __tablename__ = "tools"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(191), unique=True)
    slug: Mapped[str] = mapped_column(String(191), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    booth_url: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    search_keywords: Mapped[str | None] = mapped_column(Text)
    exclude_keywords: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Shop(Base, TimestampMixin):
    __tablename__ = "shops"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(191), index=True)
    booth_shop_id: Mapped[str | None] = mapped_column(String(191), unique=True)
    shop_url: Mapped[str | None] = mapped_column(Text)
    icon_url: Mapped[str | None] = mapped_column(Text)
    is_watch_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_excluded: Mapped[bool] = mapped_column(Boolean, default=False)


class Item(Base, TimestampMixin):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(primary_key=True)
    booth_item_id: Mapped[str | None] = mapped_column(String(191), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    item_url: Mapped[str] = mapped_column(Text)
    shop_id: Mapped[int | None] = mapped_column(ForeignKey("shops.id"), nullable=True)
    shop_name: Mapped[str | None] = mapped_column(String(191), index=True)
    shop_url: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    thumbnail_cache_path: Mapped[str | None] = mapped_column(Text)
    current_price: Mapped[int | None] = mapped_column(Integer)
    previous_price: Mapped[int | None] = mapped_column(Integer)
    lowest_price: Mapped[int | None] = mapped_column(Integer)
    highest_price: Mapped[int | None] = mapped_column(Integer)
    is_free: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_on_sale: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_nsfw: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_tool: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    category: Mapped[str | None] = mapped_column(String(191), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shop: Mapped[Shop | None] = relationship()
    tags: Mapped[list["ItemTag"]] = relationship(back_populates="item", cascade="all, delete-orphan")
    avatar_relations: Mapped[list["ItemAvatarRelation"]] = relationship(back_populates="item", cascade="all, delete-orphan")
    price_histories: Mapped[list["PriceHistory"]] = relationship(back_populates="item", cascade="all, delete-orphan")


class ItemTag(Base):
    __tablename__ = "item_tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    tag: Mapped[str] = mapped_column(String(191), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    item: Mapped[Item] = relationship(back_populates="tags")


class ItemAvatarRelation(Base, TimestampMixin):
    __tablename__ = "item_avatar_relations"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    avatar_id: Mapped[int] = mapped_column(ForeignKey("avatars.id"))
    match_type: Mapped[str] = mapped_column(String(20), default="auto")
    match_reason: Mapped[str | None] = mapped_column(Text)
    item: Mapped[Item] = relationship(back_populates="avatar_relations")
    avatar: Mapped[Avatar] = relationship()
    __table_args__ = (UniqueConstraint("item_id", "avatar_id", name="uq_item_avatar"),)


class PriceHistory(Base):
    __tablename__ = "price_histories"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    price: Mapped[int | None] = mapped_column(Integer)
    is_free: Mapped[bool] = mapped_column(Boolean, default=False)
    is_on_sale: Mapped[bool] = mapped_column(Boolean, default=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    item: Mapped[Item] = relationship(back_populates="price_histories")


class CrawlTarget(Base, TimestampMixin):
    __tablename__ = "crawl_targets"
    id: Mapped[int] = mapped_column(primary_key=True)
    target_type: Mapped[str] = mapped_column(String(20), index=True)
    target_value: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CrawlLog(Base):
    __tablename__ = "crawl_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    target_id: Mapped[int | None] = mapped_column(ForeignKey("crawl_targets.id"), nullable=True)
    target_url: Mapped[str | None] = mapped_column(Text)
    crawl_type: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), index=True)
    status_code: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    error_detail: Mapped[str | None] = mapped_column(Text)


class ErrorLog(Base):
    __tablename__ = "error_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(100), index=True)
    level: Mapped[str] = mapped_column(String(20), default="error")
    message: Mapped[str] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ThumbnailCache(Base):
    __tablename__ = "thumbnail_cache"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    original_url: Mapped[str] = mapped_column(Text)
    cache_path: Mapped[str] = mapped_column(Text)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class UserFavorite(Base):
    __tablename__ = "user_favorites"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class UserAvatarWatch(Base):
    __tablename__ = "user_avatar_watches"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    avatar_id: Mapped[int] = mapped_column(ForeignKey("avatars.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class UserShopWatch(Base):
    __tablename__ = "user_shop_watches"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class NotificationSetting(Base, TimestampMixin):
    __tablename__ = "notification_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    notify_sale: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_free: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_new: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_price_change: Mapped[bool] = mapped_column(Boolean, default=False)
    min_discount_rate: Mapped[int] = mapped_column(Integer, default=0)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    notification_type: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(String(300))
    message: Mapped[str | None] = mapped_column(Text)
    sent_to: Mapped[str | None] = mapped_column(String(191))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class RankingMetric(Base):
    __tablename__ = "ranking_metrics"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), unique=True)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    click_count: Mapped[int] = mapped_column(Integer, default=0)
    favorite_count: Mapped[int] = mapped_column(Integer, default=0)
    sale_view_count: Mapped[int] = mapped_column(Integer, default=0)
    free_view_count: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[float] = mapped_column(Float, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
