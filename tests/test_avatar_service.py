from sqlalchemy import select

from app.models import Avatar, Item, ItemAvatarRelation
from app.services.avatar_service import avatar_name_from_title, ensure_avatar_page_for_item, looks_like_avatar_product
from app.services.detection import apply_avatar_matches


def test_avatar_name_from_title_extracts_series_name():
    assert avatar_name_from_title("キプフェル Kipfel / オリジナル3Dモデル") == "キプフェル Kipfel"


def test_avatar_name_from_title_rejects_bare_numeric_artifacts():
    # These are the kind of garbage "avatar" names that used to get created
    # from titles like "《48》あばた" or "追加シェイプキー300種" once bracket
    # content or generic terms were stripped away, leaving only a version
    # number or count behind. A bare number is not a usable avatar name, and
    # it made matching very unreliable since any item mentioning that number
    # anywhere would substring-match it.
    assert avatar_name_from_title("7") is None
    assert avatar_name_from_title("300") is None
    assert avatar_name_from_title("26-s / オリジナル3Dモデル") is None


def test_looks_like_avatar_product_excludes_clothes():
    item = Item(title="キプフェル対応 衣装セット", item_url="https://booth.pm/ja/items/1", description="VRChat avatar clothes")
    assert looks_like_avatar_product(item, ["VRChat"]) is False


def test_looks_like_avatar_product_ignores_generic_description_mention():
    # A prop/accessory whose title doesn't claim to be an avatar shouldn't
    # become one just because "アバター" or "3Dモデル" is mentioned somewhere in
    # its description - that's too loose a signal and was the main source of
    # bogus Avatar entries with short, over-matching names. Note: no negative
    # term appears anywhere here, so the old behavior would have accepted
    # this purely on the description's positive-term mention.
    item = Item(
        title="全自動麻雀卓",
        item_url="https://booth.pm/ja/items/2",
        description="このアバター用の3Dモデルです",
    )
    assert looks_like_avatar_product(item, []) is False


def test_looks_like_avatar_product_accepts_booth_category_signal():
    # BOOTH's own curated category label is a reliable signal even without an
    # explicit declaration in the title itself.
    item = Item(
        title="「桔梗」",
        item_url="https://booth.pm/ja/items/3",
        category="3Dキャラクター",
    )
    assert looks_like_avatar_product(item, []) is True


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


def test_avatar_product_and_keyword_match_do_not_duplicate_relation(db_session):
    item = Item(
        title="Kipfel / オリジナル3Dモデル",
        item_url="https://booth.pm/ja/items/5813187",
        description="Kipfel VRChat avatar",
        category="3Dキャラクター",
    )
    db_session.add(item)
    db_session.commit()

    avatar = ensure_avatar_page_for_item(db_session, item, ["VRChat"])
    apply_avatar_matches(db_session, item, ["Kipfel", "VRChat"])
    db_session.commit()

    relations = db_session.scalars(select(ItemAvatarRelation).where(ItemAvatarRelation.item_id == item.id, ItemAvatarRelation.avatar_id == avatar.id)).all()
    assert len(relations) == 1
