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


def test_parse_item_detail_aggregate_offer_low_price():
    html = """
    <html><head>
      <script type="application/ld+json">
      {"@type":"Product","name":"複数価格商品","description":"説明文","image":"https://example.com/item.jpg","offers":{"@type":"AggregateOffer","lowPrice":"1500","highPrice":"3800"},"brand":{"@type":"Brand","name":"ALICE","url":"https://aliceinshelter.booth.pm/"}}
      </script>
    </head><body>
      <a href="https://booth.pm/ja/items?tags%5B%5D=VRChat"><img alt="VRChat" src="/badge.png"></a>
      <div class="variation-price">¥ 3,800</div>
      <div>発売日 2026-05-01</div>
    </body></html>
    """
    item = parse_item_detail(html, "https://booth.pm/ja/items/5615136")
    assert item.price == 1500
    assert item.shop_name == "ALICE"
    assert item.shop_url == "https://aliceinshelter.booth.pm/"
    assert item.tags == ["VRChat"]


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


def test_parse_search_results_booth_item_card():
    html = """
    <li class="item-card l-card" data-product-id="5813187" data-product-name="キプフェル Kipfel / オリジナル3Dモデル" data-product-price="5500">
      <a class="js-thumbnail-image item-card__thumbnail-image" data-original="https://booth.pximg.net/thumb.jpg" href="https://booth.pm/ja/items/5813187"></a>
      <a class="item-card__category-anchor" href="/ja/browse/3D%E3%82%AD%E3%83%A3%E3%83%A9%E3%82%AF%E3%82%BF%E3%83%BC">3Dキャラクター</a>
      <div class="l-item-card-badge"><img alt="VRChat" src="/badge.png"></div>
      <div class="item-card__title"><a href="https://booth.pm/ja/items/5813187">キプフェル Kipfel / オリジナル3Dモデル</a></div>
      <a class="item-card__shop-name-anchor" href="https://mukumi.booth.pm/"><div class="item-card__shop-name">もち山金魚</div></a>
      <div class="price">¥ 5,500</div>
    </li>
    """
    items = parse_search_results(html)
    assert len(items) == 1
    assert items[0].booth_item_id == "5813187"
    assert items[0].price == 5500
    assert items[0].image_url == "https://booth.pximg.net/thumb.jpg"
    assert items[0].shop_name == "もち山金魚"
    assert items[0].shop_url == "https://mukumi.booth.pm/"
    assert items[0].category == "3Dキャラクター"
    assert items[0].tags == ["VRChat"]
