from sqlalchemy import select

from app.models import Avatar, AvatarAlias, CrawlLog, Item, ItemAvatarRelation, Tool, now_utc
from app.services.detection import detect_avatar_matches, detect_free, detect_nsfw, detect_sale, detect_tool, reclassify_all_items


def test_sale_detection_from_price_drop():
    decision = detect_sale(current_price=1000, previous_price=1500, lowest_price=1000)
    assert decision.is_on_sale is True
    assert decision.discount_rate == 33


def test_free_detection_variants():
    assert detect_free("無料 キプフェル衣装", "", 500) is True
    assert detect_free("衣装", "期間限定無料配布です", 500) is True
    assert detect_free("衣装", "", 0) is True


def test_nsfw_detection():
    assert detect_nsfw("衣装", "R18対応", []) is True
    assert detect_nsfw("衣装", "R18ではありません", []) is False
    assert detect_nsfw("衣装", "通常商品", []) is False


def test_avatar_match_detection(db_session):
    avatar = Avatar(name="キプフェル", slug="kipfel", reading="きぷふぇる", english_name="Kipfel", search_keywords="キプフェル,Kipfel")
    db_session.add(avatar)
    db_session.flush()
    db_session.add(AvatarAlias(avatar_id=avatar.id, alias="KIPFEL"))
    db_session.commit()
    matches = detect_avatar_matches(db_session, "KIPFEL 対応衣装", "", [])
    assert [match[0].slug for match in matches] == ["kipfel"]


def test_avatar_match_still_fires_with_common_booth_suffixes(db_session):
    avatar = Avatar(name="キプフェル", slug="kipfel", search_keywords="キプフェル")
    db_session.add(avatar)
    db_session.commit()
    for title in ["キプフェル専用ネイルチップ", "【キプフェル対応】あばたーぱーつ", "キプフェル用テクスチャ"]:
        matches = detect_avatar_matches(db_session, title, "", [])
        assert [m[0].slug for m in matches] == ["kipfel"], title


def test_avatar_match_rejects_name_embedded_in_a_longer_different_name(db_session):
    # "ネコ" must not match "ネコチヤン" - that's a different avatar/product name
    # that merely happens to start with the same two characters. This is the
    # exact class of false-positive substring match that made avatar
    # assignment unreliable.
    neko = Avatar(name="ネコ", slug="neko", search_keywords="ネコ")
    db_session.add(neko)
    db_session.commit()
    matches = detect_avatar_matches(db_session, "ネコチヤン用まつげセット", "", [])
    assert matches == []


def test_avatar_match_ignores_single_character_candidates(db_session):
    # Bare single-character "avatar" names are parsing artifacts (see
    # avatar_name_from_title's own rejection of these), but even if one
    # already exists in the DB it must not match arbitrary text that happens
    # to contain that character.
    junk = Avatar(name="7", slug="7", search_keywords="7")
    db_session.add(junk)
    db_session.commit()
    matches = detect_avatar_matches(db_session, "Vket7 記念セール品", "7個セット", ["7"])
    assert matches == []


def test_avatar_match_prioritizes_tag_over_title_over_description(db_session):
    avatar = Avatar(name="キプフェル", slug="kipfel", search_keywords="キプフェル")
    db_session.add(avatar)
    db_session.commit()
    # Both the description and the tag contain a valid, isolated mention of
    # the avatar name - the match reason should reflect the tag (the
    # strongest signal), not the description, proving the priority order.
    matches = detect_avatar_matches(db_session, "無関係なタイトル", "対応アバター:キプフェル", ["キプフェル"])
    assert [m[1] for m in matches] == ["tag:キプフェル"]


def test_tool_detection(db_session):
    db_session.add(Tool(name="Modular Avatar", slug="modular-avatar", search_keywords="Modular Avatar,ModularAvatar"))
    db_session.commit()
    assert detect_tool(db_session, "Modular Avatar prefab", "", []) is True


def test_reclassify_all_items_drops_stale_auto_matches_and_keeps_manual(db_session):
    kipfel = Avatar(name="キプフェル", slug="kipfel", search_keywords="キプフェル")
    other = Avatar(name="まめひなた", slug="mamehinata", search_keywords="まめひなた")
    db_session.add_all([kipfel, other])
    db_session.flush()

    # This item has nothing to do with either avatar, but has a leftover
    # "auto" relation from the old sloppy substring matcher - it must be
    # removed since it no longer qualifies under the current rules.
    unrelated_item = Item(title="無関係な小道具セット", item_url="https://booth.pm/ja/items/1")
    db_session.add(unrelated_item)
    db_session.flush()
    db_session.add(
        ItemAvatarRelation(item_id=unrelated_item.id, avatar_id=kipfel.id, match_type="auto", match_reason="keyword:キ")
    )
    # A manually-set relation on the same item must survive reclassification.
    db_session.add(
        ItemAvatarRelation(item_id=unrelated_item.id, avatar_id=other.id, match_type="manual", match_reason="admin set")
    )

    # This item genuinely mentions the avatar and should get a fresh match.
    matching_item = Item(title="キプフェル専用ネイルチップ", item_url="https://booth.pm/ja/items/2")
    db_session.add(matching_item)
    db_session.commit()

    summary = reclassify_all_items(db_session)

    unrelated_relations = db_session.scalars(
        select(ItemAvatarRelation).where(ItemAvatarRelation.item_id == unrelated_item.id)
    ).all()
    assert [(r.avatar_id, r.match_type) for r in unrelated_relations] == [(other.id, "manual")]

    matching_relations = db_session.scalars(
        select(ItemAvatarRelation).where(ItemAvatarRelation.item_id == matching_item.id)
    ).all()
    assert len(matching_relations) == 1
    assert matching_relations[0].avatar_id == kipfel.id
    assert matching_relations[0].match_type == "auto"

    assert summary["items"] == 2
    assert summary["relations_removed"] == 1
    assert summary["relations_added"] == 1


def test_reclassify_all_items_reports_live_progress_on_log(db_session):
    # This is what the /admin/avatars/reclassify/status htmx panel polls -
    # without it being kept up to date during the run, "real-time" progress
    # would just be a single jump from "queued" to "done".
    kipfel = Avatar(name="キプフェル", slug="kipfel", search_keywords="キプフェル")
    db_session.add(kipfel)
    for i in range(3):
        db_session.add(Item(title=f"商品{i}", item_url=f"https://booth.pm/ja/items/{10 + i}"))
    db_session.commit()

    log = CrawlLog(target_url="internal:reclassify", crawl_type="reclassify", status="running", started_at=now_utc())
    db_session.add(log)
    db_session.commit()

    reclassify_all_items(db_session, log)

    assert log.item_count == 3
    assert "3/3" in log.message
