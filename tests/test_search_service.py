from app.services.search_service import parse_search_query


def test_parse_search_operators():
    parsed = parse_search_query("avatar:キプフェル free:true sale:true shop:ショップ名 tool:true tag:衣装 -r18 -対応外")
    assert parsed.avatar == "キプフェル"
    assert parsed.free is True
    assert parsed.sale is True
    assert parsed.shop == "ショップ名"
    assert parsed.tool is True
    assert parsed.tag == "衣装"
    assert parsed.exclude_terms == ["r18", "対応外"]
