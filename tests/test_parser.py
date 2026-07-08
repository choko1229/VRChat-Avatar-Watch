from app.crawler.parser import parse_item_detail, parse_search_results, parse_price, summarize_parsed_items


def test_parse_price_variants():
    assert parse_price("¥1,500") == 1500
    assert parse_price("無料") == 0
    assert parse_price("価格未定") is None


def test_parse_item_detail_json_ld_and_meta():
    html = """
    <html><head>
      <meta property="og:image" content="https://example.com/item.jpg">
      <script type="application/ld+json">
      {"@type":"Product","name":"キプフェル対応衣装","description":"説明文","image":["https://example.com/json.jpg"],"offers":{"price":"1200"}}
      </script>
    </head><body>
      <a href="https://sample.booth.pm">Sample Shop</a>
      <a href="/ja/search/%E8%A1%A3%E8%A3%85">衣装</a>
    </body></html>
    """
    item = parse_item_detail(html, "https://booth.pm/ja/items/12345")
    assert item.booth_item_id == "12345"
    assert item.title == "キプフェル対応衣装"
    assert item.description == "説明文"
    assert item.image_url == "https://example.com/json.jpg"
    assert item.price == 1200
    assert item.shop_name == "Sample Shop"
    assert item.tags == ["衣装"]


def test_parse_search_results_deduplicates_items():
    html = """
    <article>
      <a href="/ja/items/1"><img alt="商品A" src="/thumb.jpg">商品A</a>
      <span>¥500</span>
    </article>
    <article>
      <a href="/ja/items/1">商品A duplicate</a>
    </article>
    """
    items = parse_search_results(html)
    assert len(items) == 1
    assert items[0].booth_item_id == "1"
    assert items[0].image_url == "https://booth.pm/thumb.jpg"
    assert summarize_parsed_items(items)["count"] == 1
