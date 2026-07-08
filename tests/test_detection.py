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


def test_tool_detection(db_session):
    db_session.add(Tool(name="Modular Avatar", slug="modular-avatar", search_keywords="Modular Avatar,ModularAvatar"))
    db_session.commit()
    assert detect_tool(db_session, "Modular Avatar prefab", "", []) is True
