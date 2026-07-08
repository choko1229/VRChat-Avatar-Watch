from datetime import timedelta

from sqlalchemy import select

from app.models import Item, Notification, RankingMetric, Setting, ThumbnailCache, User, UserFavorite, now_utc
from app.services.notification_service import dispatch_pending_notifications
from app.services.ranking_service import ranking_items, sync_ranking_metrics
from app.services.thumbnail_service import prune_thumbnail_cache


def test_ranking_items_uses_metric_score_and_favorites(db_session):
    item = Item(title="Popular", item_url="https://booth.pm/ja/items/1")
    user = User(discord_id="1", username="tester")
    db_session.add_all([item, user])
    db_session.commit()
    db_session.add_all([RankingMetric(item_id=item.id, view_count=2), UserFavorite(user_id=user.id, item_id=item.id)])
    db_session.commit()

    sync_ranking_metrics(db_session)

    metric = db_session.scalar(select(RankingMetric).where(RankingMetric.item_id == item.id))
    assert metric.favorite_count == 1
    assert metric.score > 0
    assert ranking_items(db_session, 1)[0].id == item.id


def test_prune_thumbnail_cache_removes_expired_rows(db_session):
    item = Item(title="Cached", item_url="https://booth.pm/ja/items/2", thumbnail_cache_path="missing.jpg")
    db_session.add(item)
    db_session.commit()
    row = ThumbnailCache(
        item_id=item.id,
        original_url="https://example.com/source.jpg",
        cache_path="missing.jpg",
        file_size=10,
        expires_at=now_utc() - timedelta(days=1),
    )
    db_session.add(row)
    db_session.commit()

    assert prune_thumbnail_cache(db_session, max_gb=10) == 1
    assert db_session.get(ThumbnailCache, row.id) is None
    assert db_session.get(Item, item.id).thumbnail_cache_path is None


def test_dispatch_pending_notifications_posts_to_discord(db_session, monkeypatch):
    db_session.add(Setting(key="discord_webhook_public", value="https://discord.example/webhook", is_secret=True))
    notification = Notification(notification_type="new", title="New", message="Item")
    db_session.add(notification)
    db_session.commit()
    calls = []

    class Response:
        def raise_for_status(self):
            return None

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, json):
            calls.append((url, json))
            return Response()

    monkeypatch.setattr("app.services.notification_service.httpx.Client", Client)

    assert dispatch_pending_notifications(db_session) == 1
    assert calls == [("https://discord.example/webhook", {"content": "New\nItem"})]
    assert notification.sent_to == "discord"
    assert notification.sent_at is not None
