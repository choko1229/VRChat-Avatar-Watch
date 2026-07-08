from app.crawler.booth import BoothCrawler, is_allowed_booth_url, validate_crawl_target
from app.models import CrawlTarget, Setting, now_utc


def test_crawler_recent_target_skip_reason(db_session):
    db_session.add(Setting(key="min_crawl_interval_minutes", value="30", is_secret=False))
    target = CrawlTarget(target_type="keyword", target_value="キプフェル", last_crawled_at=now_utc())
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
