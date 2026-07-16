from app.models import Item, RankingMetric
from app.routers.public import _needs_full_detail_fetch, increment_item_metric


def test_increment_item_metric_accepts_null_counts():
    item = Item(title="Kipfel item", item_url="https://booth.pm/ja/items/80", is_on_sale=True, is_free=True)
    metric = RankingMetric(item_id=80, view_count=None, sale_view_count=None, free_view_count=None)

    increment_item_metric(metric, item)

    assert metric.view_count == 1
    assert metric.sale_view_count == 1
    assert metric.free_view_count == 1


def test_needs_full_detail_fetch_flags_missing_description():
    item = Item(title="キプフェル対応衣装", item_url="https://booth.pm/ja/items/1", description=None)
    assert _needs_full_detail_fetch(item) is True


def test_needs_full_detail_fetch_flags_truncated_title_even_with_description():
    # A description already being present used to be enough to skip
    # fetching, even if the title itself was cut off by BOOTH's search-card
    # truncation - meaning a truncated title could persist forever.
    item = Item(title="とても長いタイトルが途中で切れて...", item_url="https://booth.pm/ja/items/1", description="説明文あり")
    assert _needs_full_detail_fetch(item) is True


def test_needs_full_detail_fetch_false_when_complete():
    item = Item(title="キプフェル対応衣装", item_url="https://booth.pm/ja/items/1", description="説明文あり")
    assert _needs_full_detail_fetch(item) is False
