from sqlalchemy import select

from app.models import Avatar, Item, ItemAvatarRelation
from app.services.avatar_service import avatar_name_from_title, ensure_avatar_page_for_item, looks_like_avatar_product


def test_avatar_name_from_title_extracts_series_name():
    assert avatar_name_from_title("キプフェル Kipfel / オリジナル3Dモデル") == "キプフェル Kipfel"


def test_looks_like_avatar_product_excludes_clothes():
    item = Item(title="キプフェル対応 衣装セット", item_url="https://booth.pm/ja/items/1", description="VRChat avatar clothes")
    assert looks_like_avatar_product(item, ["VRChat"]) is False


def test_ensure_avatar_page_for_item_creates_avatar_and_relation(db_session):
    item = Item(
        title="Kipfel / オリジナル3Dモデル",
        item_url="https://booth.pm/ja/items/5813187",
        image_url="https://example.com/kipfel.jpg",
        description="VRChat向けアバター",
        category="3Dキャラクター",
    )
    db_session.add(item)
    db_session.commit()

    avatar = ensure_avatar_page_for_item(db_session, item, ["VRChat"])
    db_session.commit()

    assert avatar is not None
    assert avatar.slug == "kipfel"
    assert avatar.booth_url == item.item_url
    assert db_session.scalar(select(Avatar).where(Avatar.slug == "kipfel")) is not None
    relation = db_session.scalar(select(ItemAvatarRelation).where(ItemAvatarRelation.item_id == item.id, ItemAvatarRelation.avatar_id == avatar.id))
    assert relation is not None
    assert relation.match_reason == "avatar_product"
