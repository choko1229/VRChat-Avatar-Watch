from app.models import Item
from app.services.price_service import record_price


def test_price_history_save(db_session):
    item = Item(title="テスト商品", item_url="https://booth.pm/ja/items/1", current_price=1500, lowest_price=1500, highest_price=1500)
    db_session.add(item)
    db_session.commit()
    history = record_price(db_session, item, 1000)
    db_session.commit()
    assert history.item_id == item.id
    assert item.is_on_sale is True
    assert item.previous_price == 1500
