from sqlalchemy import select

from app.models import Avatar, Item, ItemAvatarRelation, User, UserOwnedItem
from app.services.library_service import import_owned_items, owned_items_for_user, related_items_for_owned_avatars


def _library_html(booth_item_id: str, title: str, shop_name: str, shop_url: str) -> str:
    return f"""
    <li>
      <div class="flex gap-8 desktop:gap-16 border-b border-border300 pb-16">
        <a target="_blank" rel="noopener" href="https://booth.pm/ja/items/{booth_item_id}">
          <img class="l-library-item-thumbnail" src="https://booth.pximg.net/thumb.jpg">
        </a>
        <div>
          <a class="no-underline" href="https://booth.pm/ja/items/{booth_item_id}">
            <div class="text-16">{title}</div>
          </a>
          <a class="no-underline" href="{shop_url}">
            <div class="text-14 text-text-gray600">{shop_name}</div>
          </a>
        </div>
      </div>
    </li>
    """


def test_import_owned_items_matches_avatar_and_is_idempotent(db_session):
    user = User(discord_id="1", username="tester")
    avatar = Avatar(name="キプフェル", slug="kipfel", search_keywords="キプフェル")
    db_session.add_all([user, avatar])
    db_session.commit()

    html = "<ul>" + _library_html("8629189", "キプフェル専用ヘアセット", "GLAY Unknown", "https://nakarnooo.booth.pm/") + "</ul>"

    summary = import_owned_items(db_session, user, html)
    assert summary == {"parsed": 1, "imported": 1, "matched": 1}

    owned = db_session.scalar(select(UserOwnedItem).where(UserOwnedItem.user_id == user.id))
    assert owned.booth_item_id == "8629189"
    assert owned.avatar_id == avatar.id
    assert owned.shop_name == "GLAY Unknown"

    # Re-importing the same page must not create a duplicate row or re-count
    # it as newly imported.
    summary_again = import_owned_items(db_session, user, html)
    assert summary_again == {"parsed": 1, "imported": 0, "matched": 0}
    all_owned = db_session.scalars(select(UserOwnedItem).where(UserOwnedItem.user_id == user.id)).all()
    assert len(all_owned) == 1


def test_owned_items_for_user_orders_newest_first(db_session):
    user = User(discord_id="1", username="tester")
    db_session.add(user)
    db_session.commit()
    html = "<ul>" + _library_html("1", "Item One", "Shop", "https://shop.booth.pm/") + "</ul>"
    import_owned_items(db_session, user, html)
    html2 = "<ul>" + _library_html("2", "Item Two", "Shop", "https://shop.booth.pm/") + "</ul>"
    import_owned_items(db_session, user, html2)

    items = owned_items_for_user(db_session, user)
    assert [item.booth_item_id for item in items] == ["2", "1"]


def test_related_items_for_owned_avatars_excludes_already_owned(db_session):
    user = User(discord_id="1", username="tester")
    avatar = Avatar(name="キプフェル", slug="kipfel", search_keywords="キプフェル")
    db_session.add_all([user, avatar])
    db_session.flush()

    owned_item = Item(booth_item_id="100", title="キプフェル専用アイテムA", item_url="https://booth.pm/ja/items/100")
    other_item = Item(booth_item_id="200", title="キプフェル専用アイテムB", item_url="https://booth.pm/ja/items/200")
    db_session.add_all([owned_item, other_item])
    db_session.flush()
    db_session.add_all(
        [
            ItemAvatarRelation(item_id=owned_item.id, avatar_id=avatar.id, match_type="auto", match_reason="title:キプフェル"),
            ItemAvatarRelation(item_id=other_item.id, avatar_id=avatar.id, match_type="auto", match_reason="title:キプフェル"),
        ]
    )
    db_session.add(UserOwnedItem(user_id=user.id, booth_item_id="100", title="owned", item_url="https://booth.pm/ja/items/100", avatar_id=avatar.id))
    db_session.commit()

    results = related_items_for_owned_avatars(db_session, user)
    assert len(results) == 1
    result_avatar, items = results[0]
    assert result_avatar.id == avatar.id
    assert [item.booth_item_id for item in items] == ["200"]


def test_related_items_for_owned_avatars_empty_when_nothing_matched(db_session):
    user = User(discord_id="1", username="tester")
    db_session.add(user)
    db_session.commit()
    assert related_items_for_owned_avatars(db_session, user) == []
