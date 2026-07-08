from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, selectinload

from app.crawler.parser import ParsedItem
from app.models import (
    Avatar,
    AvatarAlias,
    CrawlLog,
    CrawlTarget,
    Item,
    ItemAvatarRelation,
    ItemTag,
    Notification,
    PriceHistory,
    RankingMetric,
    Setting,
    Shop,
    ThumbnailCache,
    Tool,
    UserAvatarWatch,
    UserFavorite,
    UserShopWatch,
)
from app.services.detection import apply_avatar_matches, detect_free, detect_nsfw, detect_tool
from app.services.price_service import record_price


def parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [tag.strip() for tag in raw.replace("\n", ",").split(",") if tag.strip()]


def upsert_manual_shop(db: Session, name: str | None, shop_url: str | None = None) -> Shop | None:
    if not name:
        return None
    shop = db.scalar(select(Shop).where(Shop.name == name))
    if not shop:
        shop = Shop(name=name, shop_url=shop_url)
        db.add(shop)
        db.flush()
    elif shop_url:
        shop.shop_url = shop_url
    return shop


def create_manual_item(
    db: Session,
    *,
    title: str,
    item_url: str,
    description: str | None,
    image_url: str | None,
    shop_name: str | None,
    shop_url: str | None,
    current_price: int | None,
    category: str | None,
    tags: list[str],
    is_nsfw: bool | None = None,
    is_tool: bool | None = None,
) -> Item:
    shop = upsert_manual_shop(db, shop_name, shop_url)
    item = Item(
        title=title,
        item_url=item_url,
        description=description,
        image_url=image_url,
        shop_id=shop.id if shop else None,
        shop_name=shop_name,
        shop_url=shop_url,
        category=category,
    )
    db.add(item)
    db.flush()
    item.is_nsfw = detect_nsfw(title, description, tags) if is_nsfw is None else is_nsfw
    item.is_tool = detect_tool(db, title, description, tags) if is_tool is None else is_tool
    item.is_free = detect_free(title, description, current_price)
    for tag in tags:
        db.add(ItemTag(item_id=item.id, tag=tag))
    record_price(db, item, current_price)
    apply_avatar_matches(db, item, tags)
    db.commit()
    return item


def update_manual_item(
    db: Session,
    item: Item,
    *,
    title: str,
    item_url: str,
    description: str | None,
    image_url: str | None,
    shop_name: str | None,
    shop_url: str | None,
    current_price: int | None,
    category: str | None,
    tags: list[str],
    is_free: bool,
    is_on_sale: bool,
    is_nsfw: bool,
    is_tool: bool,
) -> Item:
    shop = upsert_manual_shop(db, shop_name, shop_url)
    item.title = title
    item.item_url = item_url
    item.description = description
    item.image_url = image_url
    item.shop_id = shop.id if shop else None
    item.shop_name = shop_name
    item.shop_url = shop_url
    item.category = category
    item.is_free = is_free
    item.is_on_sale = is_on_sale
    item.is_nsfw = is_nsfw
    item.is_tool = is_tool
    item.tags.clear()
    db.flush()
    for tag in tags:
        db.add(ItemTag(item_id=item.id, tag=tag))
    if current_price != item.current_price:
        record_price(db, item, current_price)
        item.is_free = is_free
        item.is_on_sale = is_on_sale
    db.commit()
    return item


def set_avatar_relation(db: Session, item: Item, avatar_id: int, match_type: str, note: str | None) -> ItemAvatarRelation:
    avatar = db.get(Avatar, avatar_id)
    if not avatar:
        raise ValueError("avatar not found")
    if match_type not in {"auto", "manual", "excluded"}:
        raise ValueError("invalid match type")
    relation = db.scalar(
        select(ItemAvatarRelation).where(
            ItemAvatarRelation.item_id == item.id,
            ItemAvatarRelation.avatar_id == avatar_id,
        )
    )
    if not relation:
        relation = ItemAvatarRelation(item_id=item.id, avatar_id=avatar_id)
        db.add(relation)
    relation.match_type = match_type
    relation.match_reason = note
    db.commit()
    return relation


def apply_avatar_detail(db: Session, avatar: Avatar, parsed: ParsedItem) -> Avatar:
    avatar.booth_url = parsed.item_url or avatar.booth_url
    if parsed.image_url:
        avatar.image_url = parsed.image_url
    keywords = parse_tags(avatar.search_keywords)
    for value in (avatar.name, avatar.english_name, parsed.title):
        if value and value not in keywords:
            keywords.append(value)
    avatar.search_keywords = ",".join(keywords)
    db.commit()
    return avatar


def delete_avatar_and_redistribute(db: Session, avatar: Avatar) -> int:
    affected_item_ids = list(
        dict.fromkeys(
            db.scalars(
                select(ItemAvatarRelation.item_id).where(ItemAvatarRelation.avatar_id == avatar.id)
            ).all()
        )
    )
    db.execute(delete(ItemAvatarRelation).where(ItemAvatarRelation.avatar_id == avatar.id))
    db.execute(delete(UserAvatarWatch).where(UserAvatarWatch.avatar_id == avatar.id))
    db.execute(delete(AvatarAlias).where(AvatarAlias.avatar_id == avatar.id))
    db.delete(avatar)
    db.flush()

    if affected_item_ids:
        items = db.scalars(
            select(Item)
            .where(Item.id.in_(affected_item_ids))
            .options(selectinload(Item.tags), selectinload(Item.avatar_relations))
        ).all()
        for item in items:
            apply_avatar_matches(db, item, [tag.tag for tag in item.tags])
    db.commit()
    return len(affected_item_ids)


def delete_crawl_target(db: Session, target: CrawlTarget) -> None:
    db.execute(update(CrawlLog).where(CrawlLog.target_id == target.id).values(target_id=None))
    db.delete(target)
    db.commit()


def delete_item(db: Session, item: Item) -> None:
    db.execute(delete(Notification).where(Notification.item_id == item.id))
    db.execute(delete(UserFavorite).where(UserFavorite.item_id == item.id))
    db.execute(delete(RankingMetric).where(RankingMetric.item_id == item.id))
    db.execute(delete(ThumbnailCache).where(ThumbnailCache.item_id == item.id))
    db.execute(delete(PriceHistory).where(PriceHistory.item_id == item.id))
    db.execute(delete(ItemAvatarRelation).where(ItemAvatarRelation.item_id == item.id))
    db.execute(delete(ItemTag).where(ItemTag.item_id == item.id))
    db.delete(item)
    db.commit()


def delete_tool(db: Session, tool: Tool) -> None:
    db.delete(tool)
    db.commit()


def delete_shop(db: Session, shop: Shop) -> None:
    db.execute(delete(UserShopWatch).where(UserShopWatch.shop_id == shop.id))
    db.execute(update(Item).where(Item.shop_id == shop.id).values(shop_id=None))
    db.delete(shop)
    db.commit()


def save_setting(db: Session, key: str, value: str, is_secret: bool = False) -> Setting:
    setting = db.scalar(select(Setting).where(Setting.key == key))
    if not setting:
        setting = Setting(key=key, is_secret=is_secret)
        db.add(setting)
    setting.value = value
    setting.is_secret = is_secret
    db.commit()
    return setting


def save_tool(db: Session, tool: Tool | None, **values) -> Tool:
    if tool is None:
        tool = Tool(**values)
        db.add(tool)
    else:
        for key, value in values.items():
            setattr(tool, key, value)
    db.commit()
    return tool
