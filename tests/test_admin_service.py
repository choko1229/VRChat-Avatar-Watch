from sqlalchemy import select

from app.crawler.parser import ParsedItem
from app.models import Avatar, CrawlLog, CrawlTarget, Item, ItemAvatarRelation, Setting
from app.services.admin_service import apply_avatar_detail, create_manual_item, delete_avatar_and_redistribute, delete_crawl_target, save_setting, set_avatar_relation


def test_create_manual_item_records_tags_price_and_detection(db_session):
    item = create_manual_item(
        db_session,
        title="キプフェル対応 無料衣装",
        item_url="https://booth.pm/ja/items/100",
        description="R18ではない通常商品",
        image_url="https://example.com/image.jpg",
        shop_name="テストショップ",
        shop_url="https://example.booth.pm",
        current_price=0,
        category="衣装",
        tags=["VRChat", "衣装"],
    )
    assert item.id
    assert item.is_free is True
    assert item.shop_name == "テストショップ"
    assert [tag.tag for tag in item.tags] == ["VRChat", "衣装"]
    assert len(item.price_histories) == 1


def test_set_avatar_relation_manual_and_excluded(db_session):
    avatar = Avatar(name="キプフェル", slug="kipfel")
    db_session.add(avatar)
    db_session.commit()
    item = create_manual_item(
        db_session,
        title="衣装",
        item_url="https://booth.pm/ja/items/101",
        description="",
        image_url="",
        shop_name="",
        shop_url="",
        current_price=1000,
        category="衣装",
        tags=[],
    )
    relation = set_avatar_relation(db_session, item, avatar.id, "manual", "管理者確認")
    assert relation.match_type == "manual"
    assert relation.match_reason == "管理者確認"
    relation = set_avatar_relation(db_session, item, avatar.id, "excluded", "誤判定")
    assert relation.match_type == "excluded"


def test_save_secret_setting(db_session):
    setting = save_setting(db_session, "discord_webhook_admin", "https://example.com/webhook", True)
    assert setting.is_secret is True
    assert db_session.query(Setting).filter_by(key="discord_webhook_admin").one().value.endswith("webhook")


def test_apply_avatar_detail_updates_booth_metadata(db_session):
    avatar = Avatar(name="Kipfel", slug="kipfel", search_keywords="Kipfel")
    db_session.add(avatar)
    db_session.commit()

    apply_avatar_detail(
        db_session,
        avatar,
        ParsedItem(
            booth_item_id="5813187",
            title="Kipfel / Original 3D Model",
            item_url="https://booth.pm/ja/items/5813187",
            image_url="https://example.com/kipfel.jpg",
        ),
    )

    assert avatar.booth_url == "https://booth.pm/ja/items/5813187"
    assert avatar.image_url == "https://example.com/kipfel.jpg"
    assert "Kipfel / Original 3D Model" in avatar.search_keywords


def test_delete_avatar_redistributes_affected_items(db_session):
    old_avatar = Avatar(name="Old match", slug="old-match", search_keywords="Old match")
    kipfel = Avatar(name="Kipfel", slug="kipfel", search_keywords="Kipfel")
    item = Item(title="Kipfel jacket", item_url="https://booth.pm/ja/items/200", description="")
    db_session.add_all([old_avatar, kipfel, item])
    db_session.commit()
    db_session.add(ItemAvatarRelation(item_id=item.id, avatar_id=old_avatar.id, match_type="manual"))
    db_session.commit()

    affected_count = delete_avatar_and_redistribute(db_session, old_avatar)

    assert affected_count == 1
    assert db_session.get(Avatar, old_avatar.id) is None
    relation = db_session.scalar(
        select(ItemAvatarRelation).where(
            ItemAvatarRelation.item_id == item.id,
            ItemAvatarRelation.avatar_id == kipfel.id,
        )
    )
    assert relation is not None
    assert relation.match_type == "auto"


def test_delete_crawl_target_keeps_logs_without_target_reference(db_session):
    target = CrawlTarget(target_type="keyword", target_value="VRChat")
    db_session.add(target)
    db_session.commit()
    log = CrawlLog(target_id=target.id, target_url="https://booth.pm/ja/search/VRChat", crawl_type="keyword", status="success")
    db_session.add(log)
    db_session.commit()

    delete_crawl_target(db_session, target)

    assert db_session.get(CrawlTarget, target.id) is None
    saved_log = db_session.get(CrawlLog, log.id)
    assert saved_log is not None
    assert saved_log.target_id is None
