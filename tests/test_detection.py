from app.models import Avatar, AvatarAlias, Tool
from app.services.detection import detect_avatar_matches, detect_free, detect_nsfw, detect_sale, detect_tool


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
