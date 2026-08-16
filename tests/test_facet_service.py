from sqlalchemy import select

from app.models import FacetTag, FacetTagSynonym, Item, ItemFacetTag, ItemTag
from app.services.facet_service import (
    FacetIndex,
    all_facet_tags_grouped,
    apply_facet_tags,
    popular_facet_tags,
)


def _make_facet_tag(db_session, facet_type, slug, label, synonyms):
    facet_tag = FacetTag(facet_type=facet_type, slug=slug, label=label)
    db_session.add(facet_tag)
    db_session.flush()
    for keyword, match_field in synonyms:
        db_session.add(FacetTagSynonym(facet_tag_id=facet_tag.id, keyword=keyword, match_field=match_field))
    db_session.commit()
    return facet_tag


def test_apply_facet_tags_matches_on_tag_field(db_session):
    facet_tag = _make_facet_tag(db_session, "taste", "girly", "ガーリー", [("ガーリー", "tag")])
    item = Item(title="かわいい衣装セット", item_url="https://booth.pm/ja/items/1")
    db_session.add(item)
    db_session.commit()

    apply_facet_tags(db_session, item, ["ガーリー", "セール"], FacetIndex.build(db_session))
    db_session.commit()

    assigned = db_session.scalar(
        select(ItemFacetTag).where(ItemFacetTag.item_id == item.id, ItemFacetTag.facet_tag_id == facet_tag.id)
    )
    assert assigned is not None


def test_apply_facet_tags_matches_on_category_field(db_session):
    facet_tag = _make_facet_tag(db_session, "genre", "clothing", "衣装", [("3D衣装", "category")])
    item = Item(title="サンプル", item_url="https://booth.pm/ja/items/2", category="3D衣装")
    db_session.add(item)
    db_session.commit()

    apply_facet_tags(db_session, item, [], FacetIndex.build(db_session))
    db_session.commit()

    assert db_session.scalar(
        select(ItemFacetTag).where(ItemFacetTag.item_id == item.id, ItemFacetTag.facet_tag_id == facet_tag.id)
    )


def test_apply_facet_tags_is_idempotent(db_session):
    facet_tag = _make_facet_tag(db_session, "taste", "cool", "クール", [("クール", "tag")])
    item = Item(title="クールな衣装", item_url="https://booth.pm/ja/items/3")
    db_session.add(item)
    db_session.commit()

    index = FacetIndex.build(db_session)
    apply_facet_tags(db_session, item, ["クール"], index)
    apply_facet_tags(db_session, item, ["クール"], index)
    db_session.commit()

    rows = db_session.scalars(
        select(ItemFacetTag).where(ItemFacetTag.item_id == item.id, ItemFacetTag.facet_tag_id == facet_tag.id)
    ).all()
    assert len(rows) == 1


def test_apply_facet_tags_no_match_leaves_item_untagged(db_session):
    _make_facet_tag(db_session, "taste", "cool", "クール", [("クール", "tag")])
    item = Item(title="関係ないタイトル", item_url="https://booth.pm/ja/items/4")
    db_session.add(item)
    db_session.commit()

    apply_facet_tags(db_session, item, ["ふつう"], FacetIndex.build(db_session))
    db_session.commit()

    assert db_session.scalars(select(ItemFacetTag).where(ItemFacetTag.item_id == item.id)).all() == []


def test_all_facet_tags_grouped_buckets_by_facet_type(db_session):
    _make_facet_tag(db_session, "taste", "girly", "ガーリー", [])
    _make_facet_tag(db_session, "genre", "avatar", "アバター", [])

    grouped = all_facet_tags_grouped(db_session)

    assert {ft.slug for ft in grouped["taste"]} == {"girly"}
    assert {ft.slug for ft in grouped["genre"]} == {"avatar"}


def test_popular_facet_tags_orders_by_item_count(db_session):
    popular = _make_facet_tag(db_session, "taste", "girly", "ガーリー", [])
    rare = _make_facet_tag(db_session, "taste", "cool", "クール", [])
    item1 = Item(title="a", item_url="https://booth.pm/ja/items/5")
    item2 = Item(title="b", item_url="https://booth.pm/ja/items/6")
    db_session.add_all([item1, item2])
    db_session.commit()
    db_session.add_all(
        [
            ItemFacetTag(item_id=item1.id, facet_tag_id=popular.id),
            ItemFacetTag(item_id=item2.id, facet_tag_id=popular.id),
            ItemFacetTag(item_id=item1.id, facet_tag_id=rare.id),
        ]
    )
    db_session.commit()

    results = popular_facet_tags(db_session)

    assert results[0][0].slug == "girly"
    assert results[0][1] == 2
