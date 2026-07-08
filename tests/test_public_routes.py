from app.models import Item, RankingMetric
from app.routers.public import increment_item_metric


def test_increment_item_metric_accepts_null_counts():
    item = Item(title="Kipfel item", item_url="https://booth.pm/ja/items/80", is_on_sale=True, is_free=True)
    metric = RankingMetric(item_id=80, view_count=None, sale_view_count=None, free_view_count=None)

    increment_item_metric(metric, item)

    assert metric.view_count == 1
    assert metric.sale_view_count == 1
    assert metric.free_view_count == 1
