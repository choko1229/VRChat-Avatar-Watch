from app.models import Avatar, Item, ItemAvatarRelation, Notification, NotificationSetting, Shop, User, UserAvatarWatch, UserFavorite, UserShopWatch
from app.services.notification_service import create_item_notifications
from app.services.watch_service import toggle_avatar_watch, toggle_item_favorite, toggle_shop_watch, watched_new_items


def test_avatar_watch_creates_new_item_notification(db_session):
    user = User(discord_id="100", username="tester")
    avatar = Avatar(name="Kipfel", slug="kipfel", is_active=True)
    item = Item(title="Kipfel jacket", item_url="https://booth.pm/ja/items/1", current_price=1000)
    db_session.add_all([user, avatar, item])
    db_session.commit()
    toggle_avatar_watch(db_session, user, avatar)
    db_session.add(ItemAvatarRelation(item_id=item.id, avatar_id=avatar.id, match_type="auto"))
    db_session.commit()

    created = create_item_notifications(db_session, item, is_new=True, was_free=False, was_on_sale=False, previous_price=None)
    db_session.commit()

    assert created == 1
    notification = db_session.query(Notification).one()
    assert notification.user_id == user.id
    assert notification.item_id == item.id
    assert notification.notification_type == "new"


def test_favorite_price_change_respects_notification_setting(db_session):
    user = User(discord_id="101", username="tester")
    item = Item(title="Avatar accessory", item_url="https://booth.pm/ja/items/2", current_price=800)
    db_session.add_all([user, item])
    db_session.commit()
    db_session.add(NotificationSetting(user_id=user.id, notify_price_change=True))
    db_session.commit()
    toggle_item_favorite(db_session, user, item)
    item.current_price = 500
    db_session.commit()

    created = create_item_notifications(db_session, item, is_new=False, was_free=False, was_on_sale=False, previous_price=800)
    db_session.commit()

    assert created == 1
    assert db_session.query(UserFavorite).count() == 1
    assert db_session.query(Notification).one().notification_type == "price_change"


def test_price_change_is_disabled_by_default(db_session):
    user = User(discord_id="102", username="tester")
    item = Item(title="Avatar prop", item_url="https://booth.pm/ja/items/3", current_price=700)
    db_session.add_all([user, item])
    db_session.commit()
    toggle_item_favorite(db_session, user, item)
    item.current_price = 600
    db_session.commit()

    created = create_item_notifications(db_session, item, is_new=False, was_free=False, was_on_sale=False, previous_price=700)
    db_session.commit()

    assert created == 0
    assert db_session.query(Notification).count() == 0


def test_watched_new_items_includes_watched_avatar_and_shop_items(db_session):
    user = User(discord_id="200", username="tester")
    avatar = Avatar(name="Kipfel", slug="kipfel", is_active=True)
    watched_shop = Shop(name="watched-shop")
    unrelated_shop = Shop(name="unrelated-shop")
    db_session.add_all([user, avatar, watched_shop, unrelated_shop])
    db_session.flush()
    toggle_avatar_watch(db_session, user, avatar)
    toggle_shop_watch(db_session, user, watched_shop)

    via_avatar = Item(title="Kipfel jacket", item_url="https://booth.pm/ja/items/1", shop_id=unrelated_shop.id)
    via_shop = Item(title="Shop exclusive", item_url="https://booth.pm/ja/items/2", shop_id=watched_shop.id)
    unrelated_item = Item(title="Nothing to do with either", item_url="https://booth.pm/ja/items/3", shop_id=unrelated_shop.id)
    db_session.add_all([via_avatar, via_shop, unrelated_item])
    db_session.flush()
    db_session.add(ItemAvatarRelation(item_id=via_avatar.id, avatar_id=avatar.id, match_type="auto"))
    db_session.commit()

    results = watched_new_items(db_session, user)

    assert {item.id for item in results} == {via_avatar.id, via_shop.id}


def test_watched_new_items_excludes_excluded_avatar_relations(db_session):
    user = User(discord_id="201", username="tester")
    avatar = Avatar(name="Kipfel", slug="kipfel", is_active=True)
    db_session.add_all([user, avatar])
    db_session.flush()
    toggle_avatar_watch(db_session, user, avatar)
    item = Item(title="Falsely matched item", item_url="https://booth.pm/ja/items/9")
    db_session.add(item)
    db_session.flush()
    db_session.add(ItemAvatarRelation(item_id=item.id, avatar_id=avatar.id, match_type="excluded"))
    db_session.commit()

    assert watched_new_items(db_session, user) == []
