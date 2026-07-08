from app.models import Avatar, Setting
from app.services.admin_service import create_manual_item, save_setting, set_avatar_relation


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
