from datetime import datetime

import pytest

from app.crawler.booth import BoothCrawler, merge_parsed_item, is_allowed_booth_url, validate_crawl_target
from app.crawler.parser import ParsedItem
from app.models import CrawlLog, CrawlTarget, ErrorLog, Setting, now_utc


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


def test_validate_crawl_target_rejects_external_url():
    assert validate_crawl_target("keyword", "キプフェル") is None
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
