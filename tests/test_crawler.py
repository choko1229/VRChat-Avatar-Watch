from datetime import datetime

import pytest
from sqlalchemy import select

from app.crawler.booth import BoothCrawler, merge_parsed_item, search_page_url, is_allowed_booth_url, validate_crawl_target
from app.crawler.parser import ParsedItem
from app.models import CrawlLog, CrawlTarget, ErrorLog, Item, Setting, now_utc


def _search_result_html(product_id: str, title: str) -> str:
    return f"""
    <html><body>
      <li class="item-card" data-product-id="{product_id}">
        <div class="item-card__title"><a href="/ja/items/{product_id}">{title}</a></div>
      </li>
    </body></html>
    """


def test_crawler_recent_target_skip_reason(db_session):
    db_session.add(Setting(key="min_crawl_interval_minutes", value="30", is_secret=False))
    target = CrawlTarget(target_type="keyword", target_value="キプフェル", last_crawled_at=now_utc())
    db_session.add(target)
    db_session.commit()
    crawler = BoothCrawler(db_session, create_client=False)
    reason = crawler.skip_reason_for_recent_target(target)
    assert reason
    assert "minimum crawl interval" in reason


def test_crawler_recent_target_skip_reason_accepts_naive_datetime(db_session):
    db_session.add(Setting(key="min_crawl_interval_minutes", value="30", is_secret=False))
    target = CrawlTarget(target_type="keyword", target_value="キプフェル", last_crawled_at=datetime.now())
    db_session.add(target)
    db_session.commit()
    crawler = BoothCrawler(db_session, create_client=False)
    reason = crawler.skip_reason_for_recent_target(target)
    assert reason
    assert "minimum crawl interval" in reason


def test_booth_url_allowlist():
    assert is_allowed_booth_url("https://booth.pm/ja/items/1") is True
    assert is_allowed_booth_url("https://sample.booth.pm/items/1") is True
    assert is_allowed_booth_url("https://example.com/items/1") is False
    assert is_allowed_booth_url("file:///etc/passwd") is False


def test_search_page_url_preserves_query():
    assert search_page_url("https://booth.pm/ja/search/VRChat?tags%5B%5D=VRChat", 3) == "https://booth.pm/ja/search/VRChat?tags%5B%5D=VRChat&page=3"


def test_validate_crawl_target_rejects_external_url():
    assert validate_crawl_target("keyword", "キプフェル") is None
    assert validate_crawl_target("avatar", "キプフェル") is not None
    assert validate_crawl_target("url", "https://booth.pm/ja/items/1") is None
    assert validate_crawl_target("shop", "https://sample.booth.pm") is None
    assert validate_crawl_target("url", "https://example.com") is not None


def test_merge_parsed_item_prefers_detail_fields():
    base = ParsedItem(
        booth_item_id="1",
        title="Search title",
        item_url="https://booth.pm/ja/items/1",
        price=None,
        tags=["VRChat"],
    )
    detail = ParsedItem(
        booth_item_id="1",
        title="Detail title",
        item_url="https://booth.pm/ja/items/1",
        description="Detailed description",
        price=1200,
        tags=["VRChat", "Kipfel"],
    )

    merged = merge_parsed_item(base, detail)

    assert merged.title == "Detail title"
    assert merged.description == "Detailed description"
    assert merged.price == 1200
    assert merged.tags == ["VRChat", "Kipfel"]


class ClosingClient:
    async def aclose(self):
        raise RuntimeError("unable to perform operation on <TCPTransport closed=True>; the handler is closed")


@pytest.mark.asyncio
async def test_crawler_close_ignores_already_closed_transport(db_session):
    crawler = BoothCrawler(db_session, create_client=False)
    crawler.client = ClosingClient()

    await crawler.close()


class FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


def test_request_interval_ms_defaults_and_clamps(db_session):
    crawler = BoothCrawler(db_session, create_client=False)
    assert crawler.request_interval_ms() == 1000

    db_session.add(Setting(key="crawl_request_interval_ms", value="250", is_secret=False))
    db_session.commit()
    assert crawler.request_interval_ms() == 250

    setting = db_session.query(Setting).filter_by(key="crawl_request_interval_ms").one()
    setting.value = "999999"
    db_session.commit()
    assert crawler.request_interval_ms() == 60000


class FakeRobotsClient:
    def __init__(self):
        self.calls = 0

    async def get(self, url):
        self.calls += 1
        return FakeResponse(200, "User-agent: *\nAllow: /")


@pytest.mark.asyncio
async def test_robots_allows_url_fetches_robots_txt_only_once(db_session):
    crawler = BoothCrawler(db_session, create_client=False)
    crawler.client = FakeRobotsClient()

    for _ in range(5):
        assert await crawler.robots_allows_url("https://booth.pm/ja/items/1") is True

    assert crawler.client.calls == 1


@pytest.mark.asyncio
async def test_crawl_target_logs_deferred_status(db_session, monkeypatch):
    target = CrawlTarget(target_type="keyword", target_value="キプフェル")
    db_session.add(target)
    db_session.commit()
    crawler = BoothCrawler(db_session, create_client=False)

    async def allows(url):
        return True

    async def fetch(url):
        return FakeResponse(429)

    monkeypatch.setattr(crawler, "robots_allows_url", allows)
    monkeypatch.setattr(crawler, "fetch", fetch)

    result = await crawler.crawl_target(target, force=True)

    assert result.status == "deferred"
    assert result.status_code == 429
    log = db_session.query(CrawlLog).one()
    assert log.status == "deferred"
    error = db_session.query(ErrorLog).one()
    assert error.level == "warning"
    assert "status_code=429" in error.detail


@pytest.mark.asyncio
async def test_enrich_parsed_items_fetches_missing_detail(db_session, monkeypatch):
    db_session.add(Setting(key="crawl_request_interval_ms", value="0", is_secret=False))
    db_session.commit()
    crawler = BoothCrawler(db_session, create_client=False)
    base = ParsedItem(booth_item_id="1", title="Search title", item_url="https://booth.pm/ja/items/1", tags=["VRChat"])

    async def allows(url):
        return True

    async def fetch(url):
        return FakeResponse(
            200,
            """
            <html><head>
              <script type="application/ld+json">
              {"@type":"Product","name":"Detail title","description":"Detailed description","offers":{"price":"1300"}}
              </script>
            </head><body><a href="/ja/search/Kipfel">Kipfel</a></body></html>
            """,
        )

    monkeypatch.setattr(crawler, "robots_allows_url", allows)
    monkeypatch.setattr(crawler, "fetch", fetch)

    enriched = await crawler.enrich_parsed_items([base])

    assert enriched[0].title == "Detail title"
    assert enriched[0].description == "Detailed description"
    assert enriched[0].price == 1300


@pytest.mark.asyncio
async def test_collect_search_items_persists_each_page_before_the_next_fetch(db_session, monkeypatch):
    # max_detail_pages_per_crawl defaults to 0 candidates found here (items
    # have no missing fields we care about for this test), so enrichment is a
    # no-op and we're purely exercising the page-by-page persistence.
    db_session.add(Setting(key="crawl_request_interval_ms", value="0", is_secret=False))
    db_session.add(Setting(key="max_search_pages_per_crawl", value="2", is_secret=False))
    db_session.add(Setting(key="max_detail_pages_per_crawl", value="0", is_secret=False))
    db_session.commit()
    crawler = BoothCrawler(db_session, create_client=False)

    seen_before_page_two_fetch = {}

    async def allows(url):
        return True

    async def fetch(url):
        if "page=2" in url:
            # Page 1's item must already be committed by the time we're about
            # to fetch page 2 - that's the whole point of saving per page.
            seen_before_page_two_fetch["item_1_saved"] = bool(
                db_session.scalar(select(Item).where(Item.booth_item_id == "1"))
            )
            return FakeResponse(200, _search_result_html("2", "Second page item"))
        return FakeResponse(200, "")

    monkeypatch.setattr(crawler, "robots_allows_url", allows)
    monkeypatch.setattr(crawler, "fetch", fetch)

    first_html = _search_result_html("1", "First page item")
    items, saved_count = await crawler.collect_search_items(
        "https://booth.pm/ja/search/VRChat?tags%5B%5D=VRChat", first_html, persist=True
    )

    assert seen_before_page_two_fetch["item_1_saved"] is True
    assert saved_count == 2
    assert {item.booth_item_id for item in items} == {"1", "2"}
    assert db_session.scalar(select(Item).where(Item.booth_item_id == "2")) is not None
