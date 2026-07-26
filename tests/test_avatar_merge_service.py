from sqlalchemy import select

from app.models import Avatar, AvatarAlias, Item, ItemAvatarRelation, User, UserAvatarWatch
from app.services.avatar_merge_service import find_duplicate_avatar_groups, merge_avatars


def test_avatars_sharing_an_alias_are_grouped_as_duplicates(db_session):
    primary = Avatar(name="キプフェル", slug="kipfel", search_keywords="キプフェル")
    dup = Avatar(name="Kipfel", slug="kipfel-en", search_keywords="Kipfel")
    unrelated = Avatar(name="まめひなた", slug="mamehinata", search_keywords="まめひなた")
    db_session.add_all([primary, dup, unrelated])
    db_session.flush()
    # Both avatars carry an alias for the other's name - the exact-overlap
    # signal find_duplicate_avatar_groups looks for.
    db_session.add(AvatarAlias(avatar_id=primary.id, alias="Kipfel"))
    db_session.add(AvatarAlias(avatar_id=dup.id, alias="キプフェル"))
    db_session.commit()

    groups = find_duplicate_avatar_groups(db_session)

    assert len(groups) == 1
    grouped_ids = {avatar.id for avatar, _ in groups[0].avatars}
    assert grouped_ids == {primary.id, dup.id}
    assert unrelated.id not in grouped_ids


def test_avatars_with_no_overlap_are_not_grouped(db_session):
    a = Avatar(name="キプフェル", slug="kipfel", search_keywords="キプフェル")
    b = Avatar(name="まめひなた", slug="mamehinata", search_keywords="まめひなた")
    db_session.add_all([a, b])
    db_session.commit()

    assert find_duplicate_avatar_groups(db_session) == []


def test_merge_avatars_repoints_relations_and_drops_conflicts(db_session):
    primary = Avatar(name="キプフェル", slug="kipfel", search_keywords="キプフェル")
    dup = Avatar(name="Kipfel", slug="kipfel-en", search_keywords="Kipfel")
    db_session.add_all([primary, dup])
    db_session.flush()

    # Item A is only linked to the duplicate - its relation should move.
    item_a = Item(title="商品A", item_url="https://booth.pm/ja/items/1")
    # Item B is linked to BOTH - the duplicate's relation is redundant and
    # must be dropped rather than violate the (item_id, avatar_id) unique
    # constraint by trying to repoint it too.
    item_b = Item(title="商品B", item_url="https://booth.pm/ja/items/2")
    db_session.add_all([item_a, item_b])
    db_session.flush()
    db_session.add(ItemAvatarRelation(item_id=item_a.id, avatar_id=dup.id, match_type="auto"))
    db_session.add(ItemAvatarRelation(item_id=item_b.id, avatar_id=dup.id, match_type="auto"))
    db_session.add(ItemAvatarRelation(item_id=item_b.id, avatar_id=primary.id, match_type="manual"))
    db_session.commit()

    repointed = merge_avatars(db_session, primary, [dup])

    assert repointed == 1
    remaining_relations = db_session.scalars(select(ItemAvatarRelation)).all()
    assert len(remaining_relations) == 2
    assert {(r.item_id, r.avatar_id) for r in remaining_relations} == {(item_a.id, primary.id), (item_b.id, primary.id)}
    # The manual relation on item B must survive untouched, not get
    # overwritten by the duplicate's weaker auto match.
    item_b_relation = next(r for r in remaining_relations if r.item_id == item_b.id)
    assert item_b_relation.match_type == "manual"

    assert db_session.get(Avatar, dup.id) is None
    # The duplicate's own name is now searchable as an alias of primary.
    primary_aliases = {a.alias for a in db_session.scalars(select(AvatarAlias).where(AvatarAlias.avatar_id == primary.id)).all()}
    assert "Kipfel" in primary_aliases


def test_merge_avatars_repoints_watches_and_drops_conflicts(db_session):
    primary = Avatar(name="キプフェル", slug="kipfel", search_keywords="キプフェル")
    dup = Avatar(name="Kipfel", slug="kipfel-en", search_keywords="Kipfel")
    user1 = User(discord_id="u1", username="u1")
    user2 = User(discord_id="u2", username="u2")
    db_session.add_all([primary, dup, user1, user2])
    db_session.flush()
    # user1 only watches the duplicate - should be repointed to primary.
    db_session.add(UserAvatarWatch(user_id=user1.id, avatar_id=dup.id))
    # user2 watches both - the duplicate's watch is redundant and dropped.
    db_session.add(UserAvatarWatch(user_id=user2.id, avatar_id=dup.id))
    db_session.add(UserAvatarWatch(user_id=user2.id, avatar_id=primary.id))
    db_session.commit()

    merge_avatars(db_session, primary, [dup])

    watches = db_session.scalars(select(UserAvatarWatch)).all()
    assert len(watches) == 2
    assert {(w.user_id, w.avatar_id) for w in watches} == {(user1.id, primary.id), (user2.id, primary.id)}
