from sqlalchemy import select

from app.models import Avatar, Item, ItemAvatarRelation
from app.services.avatar_service import (
    avatar_name_from_title,
    ensure_avatar_page_for_item,
    featured_avatars,
    find_low_confidence_avatars,
    is_suspicious_avatar_name,
    looks_like_avatar_product,
)
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


def test_is_suspicious_avatar_name_flags_truncated_and_mashed_up_names():
    # Real garbage seen in production: a title mentioning several avatars
    # got parsed into one bogus "avatar" of its own, and BOOTH's own
    # ellipsis-truncated titles became names ending mid-word.
    assert is_suspicious_avatar_name("うささき・キプフェル・まめひなた・アズキ専用") is True
    assert is_suspicious_avatar_name("ぐるぐるツノのサーティーン 🌱まめふれんず共...") is True
    assert is_suspicious_avatar_name("キプフェル") is False
    # A single "・" is a common Japanese convention for a foreign-style
    # first/last name divider, not a list of unrelated names - must not
    # be flagged on that alone.
    assert is_suspicious_avatar_name("レン・キサラギ") is False


def test_is_suspicious_avatar_name_flags_non_character_product_titles():
    # A production audit of 3258 avatars with 0-1 items found whole
    # categories of non-character titles parsed into "avatars" the same
    # way: accessories/poses/gimmicks that enumerate variations in their
    # own title, and creator/shop handles.
    assert is_suspicious_avatar_name("02 ラウンドブーツ 2種 3色") is True
    assert is_suspicious_avatar_name("指輪　二種") is True
    assert is_suspicious_avatar_name("撮影向け！ポーズアニメーション15種") is True
    assert is_suspicious_avatar_name("指ハート ジェスチャー") is True
    assert is_suspicious_avatar_name("#MxU工房") is True
    assert is_suspicious_avatar_name("06") is True  # digits only, predates the creation-side guard
    assert is_suspicious_avatar_name("想定モデル") is True
    # Real, if obscure, character names must not be swept up by any of these.
    assert is_suspicious_avatar_name("マヌカ") is False
    assert is_suspicious_avatar_name("ネメシス") is False
    assert is_suspicious_avatar_name('"Duminous"') is False


def test_find_low_confidence_avatars_only_returns_items_at_or_below_threshold(db_session):
    lonely = Avatar(name="うささき・キプフェル・まめひなた・アズキ専用", slug="mashup", search_keywords="mashup")
    popular = Avatar(name="キプフェル", slug="kipfel", search_keywords="キプフェル")
    db_session.add_all([lonely, popular])
    db_session.flush()

    lonely_item = Item(title=lonely.name, item_url="https://booth.pm/ja/items/1")
    popular_item_1 = Item(title="キプフェル / オリジナル3Dモデル", item_url="https://booth.pm/ja/items/2")
    popular_item_2 = Item(title="キプフェル専用ネイルチップ", item_url="https://booth.pm/ja/items/3")
    db_session.add_all([lonely_item, popular_item_1, popular_item_2])
    db_session.flush()
    db_session.add_all(
        [
            ItemAvatarRelation(item_id=lonely_item.id, avatar_id=lonely.id, match_type="auto"),
            ItemAvatarRelation(item_id=popular_item_1.id, avatar_id=popular.id, match_type="auto"),
            ItemAvatarRelation(item_id=popular_item_2.id, avatar_id=popular.id, match_type="auto"),
        ]
    )
    db_session.commit()

    results = find_low_confidence_avatars(db_session)

    assert [r.avatar.slug for r in results] == ["mashup"]
    assert results[0].item_count == 1
    assert results[0].suspicious is True


def test_featured_avatars_orders_by_item_count_descending(db_session):
    popular = Avatar(name="キプフェル", slug="kipfel", search_keywords="キプフェル")
    quiet = Avatar(name="まめひなた", slug="mamehinata", search_keywords="まめひなた")
    db_session.add_all([popular, quiet])
    db_session.flush()
    for i in range(3):
        item = Item(title=f"popular item {i}", item_url=f"https://booth.pm/ja/items/{i}")
        db_session.add(item)
        db_session.flush()
        db_session.add(ItemAvatarRelation(item_id=item.id, avatar_id=popular.id, match_type="auto"))
    quiet_item = Item(title="quiet item", item_url="https://booth.pm/ja/items/9")
    db_session.add(quiet_item)
    db_session.flush()
    db_session.add(ItemAvatarRelation(item_id=quiet_item.id, avatar_id=quiet.id, match_type="auto"))
    db_session.commit()

    results = featured_avatars(db_session)

    assert [(avatar.slug, count) for avatar, count in results] == [("kipfel", 3), ("mamehinata", 1)]


def test_featured_avatars_ignores_excluded_relations(db_session):
    avatar = Avatar(name="キプフェル", slug="kipfel", search_keywords="キプフェル")
    db_session.add(avatar)
    db_session.flush()
    item = Item(title="excluded item", item_url="https://booth.pm/ja/items/1")
    db_session.add(item)
    db_session.flush()
    db_session.add(ItemAvatarRelation(item_id=item.id, avatar_id=avatar.id, match_type="excluded"))
    db_session.commit()

    assert featured_avatars(db_session) == []
