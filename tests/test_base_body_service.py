from sqlalchemy import select

from app.models import Avatar, BaseBody, Item, ItemAvatarRelation, ItemTag
from app.services.base_body_service import apply_base_body_group, detect_base_body_candidates, list_base_bodies_with_counts


def _make_item_with_tags(db_session, title: str, avatar: Avatar, tags: list[str], match_type: str = "auto") -> Item:
    item = Item(title=title, item_url=f"https://booth.pm/ja/items/{title}")
    db_session.add(item)
    db_session.flush()
    for tag in tags:
        db_session.add(ItemTag(item_id=item.id, tag=tag))
    db_session.add(ItemAvatarRelation(item_id=item.id, avatar_id=avatar.id, match_type=match_type))
    db_session.commit()
    return item


def test_detects_tag_shared_across_multiple_avatars_as_base_body_candidate(db_session):
    hinata = Avatar(name="まめひなた", slug="mamehinata", search_keywords="まめひなた")
    mameda = Avatar(name="まめだ", slug="mameda", search_keywords="まめだ")
    db_session.add_all([hinata, mameda])
    db_session.commit()
    _make_item_with_tags(db_session, "衣装A", hinata, ["まめふれんず", "MameFriends", "まめひなた対応"])
    _make_item_with_tags(db_session, "衣装B", mameda, ["まめふれんず", "まめだ対応"])

    candidates = detect_base_body_candidates(db_session)

    tags_found = {c.tag for c in candidates}
    assert "まめふれんず" in tags_found
    matched = next(c for c in candidates if c.tag == "まめふれんず")
    assert {avatar.slug for avatar, _ in matched.avatars} == {"mamehinata", "mameda"}
    # avatar-specific tags mentioning only one avatar must not appear as
    # candidates - there's nothing to group them with.
    assert "まめひなた対応" not in tags_found
    assert "まめだ対応" not in tags_found


def test_avatar_own_name_tag_is_not_treated_as_a_shared_signal(db_session):
    # If a seller tags an item with the avatar's own name, that's a
    # self-reference, not evidence of a *different*, shared base body.
    hinata = Avatar(name="まめひなた", slug="mamehinata", search_keywords="まめひなた")
    other = Avatar(name="キプフェル", slug="kipfel", search_keywords="キプフェル")
    db_session.add_all([hinata, other])
    db_session.commit()
    _make_item_with_tags(db_session, "衣装A", hinata, ["まめひなた"])
    _make_item_with_tags(db_session, "衣装B", other, ["まめひなた"])  # coincidental mention, still not a real base body

    candidates = detect_base_body_candidates(db_session)

    # "まめひなた" is hinata's own name, so it's excluded for hinata; only one
    # other avatar (other) is left tagging it, which is below the minimum of 2.
    assert not any(c.tag == "まめひなた" for c in candidates)


def test_booth_category_sidebar_counts_scraped_as_tags_are_never_candidates(db_session):
    # BOOTH's own category-browse sidebar gets scraped as if it were a
    # per-item tag list (see app/crawler/parser.py), producing entries like
    # "3D衣装(3575)" - a category label plus BOOTH's own count for that
    # category, identical across huge numbers of unrelated items. Without
    # filtering these out they'd bury genuine candidates like "まめふれんず".
    hinata = Avatar(name="まめひなた", slug="mamehinata", search_keywords="まめひなた")
    mameda = Avatar(name="まめだ", slug="mameda", search_keywords="まめだ")
    db_session.add_all([hinata, mameda])
    db_session.commit()
    _make_item_with_tags(db_session, "衣装A", hinata, ["3D衣装(3575)", "まめふれんず"])
    _make_item_with_tags(db_session, "衣装B", mameda, ["3D衣装(3575)", "まめふれんず"])

    candidates = detect_base_body_candidates(db_session)

    tags_found = {c.tag for c in candidates}
    assert "3D衣装(3575)" not in tags_found
    assert "まめふれんず" in tags_found


def test_generic_marketplace_tags_are_never_candidates(db_session):
    hinata = Avatar(name="まめひなた", slug="mamehinata", search_keywords="まめひなた")
    mameda = Avatar(name="まめだ", slug="mameda", search_keywords="まめだ")
    db_session.add_all([hinata, mameda])
    db_session.commit()
    _make_item_with_tags(db_session, "衣装A", hinata, ["VRChat", "3Dモデル"])
    _make_item_with_tags(db_session, "衣装B", mameda, ["VRChat", "3Dモデル"])

    candidates = detect_base_body_candidates(db_session)

    assert candidates == []


def test_generic_product_category_words_are_never_candidates(db_session):
    # "衣装" (costume/clothing) is a common word any seller might tag any
    # clothing item with, regardless of which avatar it's for - verified
    # against production data where it grouped 4 completely unrelated
    # avatars (including a non-avatar "アクリルキーホルダー" entry) with only
    # 1 supporting item each, a textbook false positive.
    hinata = Avatar(name="まめひなた", slug="mamehinata", search_keywords="まめひなた")
    kipfel = Avatar(name="キプフェル", slug="kipfel", search_keywords="キプフェル")
    db_session.add_all([hinata, kipfel])
    db_session.commit()
    _make_item_with_tags(db_session, "商品A", hinata, ["衣装"])
    _make_item_with_tags(db_session, "商品B", kipfel, ["衣装"])

    candidates = detect_base_body_candidates(db_session)

    assert candidates == []


def test_excluded_relations_do_not_contribute_to_candidates(db_session):
    hinata = Avatar(name="まめひなた", slug="mamehinata", search_keywords="まめひなた")
    mameda = Avatar(name="まめだ", slug="mameda", search_keywords="まめだ")
    db_session.add_all([hinata, mameda])
    db_session.commit()
    _make_item_with_tags(db_session, "衣装A", hinata, ["まめふれんず"])
    _make_item_with_tags(db_session, "衣装B", mameda, ["まめふれんず"], match_type="excluded")

    candidates = detect_base_body_candidates(db_session)

    assert candidates == []  # only one non-excluded avatar left, below the minimum of 2


def test_apply_base_body_group_creates_group_and_reuses_it_on_reapply(db_session):
    hinata = Avatar(name="まめひなた", slug="mamehinata", search_keywords="まめひなた")
    mameda = Avatar(name="まめだ", slug="mameda", search_keywords="まめだ")
    db_session.add_all([hinata, mameda])
    db_session.commit()

    base_body = apply_base_body_group(db_session, "まめふれんず", [hinata.id, mameda.id])

    db_session.refresh(hinata)
    db_session.refresh(mameda)
    assert hinata.base_body_id == base_body.id
    assert mameda.base_body_id == base_body.id

    second_call = apply_base_body_group(db_session, "まめふれんず", [hinata.id])
    assert second_call.id == base_body.id  # reused, not duplicated
    assert db_session.scalar(select(BaseBody).where(BaseBody.name == "まめふれんず")) is not None
    assert len(db_session.scalars(select(BaseBody)).all()) == 1


def test_avatar_already_assigned_a_base_body_is_excluded_from_future_candidates(db_session):
    hinata = Avatar(name="まめひなた", slug="mamehinata", search_keywords="まめひなた")
    mameda = Avatar(name="まめだ", slug="mameda", search_keywords="まめだ")
    akyo = Avatar(name="まめAkyo", slug="mame-akyo", search_keywords="まめAkyo")
    db_session.add_all([hinata, mameda, akyo])
    db_session.commit()
    _make_item_with_tags(db_session, "衣装A", hinata, ["まめふれんず"])
    _make_item_with_tags(db_session, "衣装B", mameda, ["まめふれんず"])
    _make_item_with_tags(db_session, "衣装C", akyo, ["まめふれんず"])

    apply_base_body_group(db_session, "まめふれんず", [hinata.id, mameda.id])
    candidates = detect_base_body_candidates(db_session)

    # akyo is still unassigned and should still be offered as a candidate,
    # but alone it's now below the minimum of 2 since hinata/mameda are gone.
    assert not any(c.tag == "まめふれんず" for c in candidates)


def test_list_base_bodies_with_counts_reports_distinct_item_count(db_session):
    hinata = Avatar(name="まめひなた", slug="mamehinata", search_keywords="まめひなた")
    mameda = Avatar(name="まめだ", slug="mameda", search_keywords="まめだ")
    db_session.add_all([hinata, mameda])
    db_session.commit()
    base_body = apply_base_body_group(db_session, "まめふれんず", [hinata.id, mameda.id])

    only_hinata = Item(title="商品A", item_url="https://booth.pm/ja/items/1")
    shared_item = Item(title="商品B", item_url="https://booth.pm/ja/items/2")
    db_session.add_all([only_hinata, shared_item])
    db_session.flush()
    db_session.add(ItemAvatarRelation(item_id=only_hinata.id, avatar_id=hinata.id, match_type="auto"))
    # An accessory compatible with both variant characters must only be
    # counted once, not once per avatar it's linked to.
    db_session.add(ItemAvatarRelation(item_id=shared_item.id, avatar_id=hinata.id, match_type="auto"))
    db_session.add(ItemAvatarRelation(item_id=shared_item.id, avatar_id=mameda.id, match_type="auto"))
    db_session.commit()

    results = list_base_bodies_with_counts(db_session)

    assert [(bb.id, avatar_count, item_count) for bb, avatar_count, item_count in results] == [(base_body.id, 2, 2)]


def test_list_base_bodies_with_counts_handles_group_with_no_items_yet(db_session):
    hinata = Avatar(name="まめひなた", slug="mamehinata", search_keywords="まめひなた")
    mameda = Avatar(name="まめだ", slug="mameda", search_keywords="まめだ")
    db_session.add_all([hinata, mameda])
    db_session.commit()
    apply_base_body_group(db_session, "まめふれんず", [hinata.id, mameda.id])

    results = list_base_bodies_with_counts(db_session)

    assert [(avatar_count, item_count) for _, avatar_count, item_count in results] == [(2, 0)]
