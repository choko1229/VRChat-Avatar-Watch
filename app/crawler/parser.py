from __future__ import annotations

import re
import json
from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup


@dataclass
class ParsedItem:
    booth_item_id: str | None
    title: str
    item_url: str
    image_url: str | None = None
    shop_name: str | None = None
    shop_url: str | None = None
    description: str | None = None
    price: int | None = None
    tags: list[str] = field(default_factory=list)
    category: str | None = None
    has_sale_label: bool = False


def parse_price(text: str | None) -> int | None:
    if not text:
        return None
    if "無料" in text:
        return 0
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def absolute_url(url: str | None, base_url: str = "https://booth.pm") -> str | None:
    if not url:
        return None
    return urljoin(base_url, url)


def booth_item_id(url: str) -> str | None:
    match = re.search(r"/items/(\d+)", url)
    return match.group(1) if match else None


def _meta_content(soup: BeautifulSoup, *selectors: str) -> str | None:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            value = node.get("content") or node.get_text(" ", strip=True)
            if value:
                return value.strip()
    return None


def _json_ld_objects(soup: BeautifulSoup) -> list[dict]:
    objects: list[dict] = []
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if isinstance(candidate, dict):
                objects.append(candidate)
    return objects


def _first_json_ld_product(soup: BeautifulSoup) -> dict:
    for obj in _json_ld_objects(soup):
        graph = obj.get("@graph")
        candidates = graph if isinstance(graph, list) else [obj]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("@type") in {"Product", "IndividualProduct"}:
                return candidate
    return {}


def parse_search_results(html: str, base_url: str = "https://booth.pm") -> list[ParsedItem]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[ParsedItem] = []
    for link in soup.select('a[href*="/items/"]'):
        href = link.get("href") or ""
        if not href:
            continue
        url = absolute_url(href, base_url) or ""
        title = link.get_text(" ", strip=True)
        if not title:
            image = link.select_one("img[alt]")
            title = image.get("alt", "") if image else ""
        if not title:
            continue
        card = link.find_parent(["li", "div", "article"]) or link
        img = card.select_one("img")
        price_text = card.get_text(" ", strip=True)
        parsed = ParsedItem(
            booth_item_id=booth_item_id(url),
            title=title[:300],
            item_url=url,
            image_url=absolute_url((img.get("src") or img.get("data-src")) if img else None, base_url),
            price=parse_price(price_text),
            has_sale_label=("SALE" in price_text.upper() or "セール" in price_text),
        )
        if parsed.booth_item_id and all(existing.booth_item_id != parsed.booth_item_id for existing in items):
            items.append(parsed)
    return items


def parse_item_detail(html: str, item_url: str) -> ParsedItem:
    soup = BeautifulSoup(html, "html.parser")
    product = _first_json_ld_product(soup)
    title = product.get("name") or _meta_content(soup, "h1", "meta[property='og:title']", "meta[name='twitter:title']") or "BOOTH Item"
    image_value = product.get("image") or _meta_content(soup, "meta[property='og:image']", "meta[name='twitter:image']")
    if isinstance(image_value, list):
        image_value = image_value[0] if image_value else None
    description_value = product.get("description") or _meta_content(soup, "meta[property='og:description']", "meta[name='description']")
    offers = product.get("offers") if isinstance(product.get("offers"), dict) else {}
    price = parse_price(str(offers.get("price"))) if offers.get("price") is not None else None
    if price is None:
        price = parse_price(_meta_content(soup, "meta[property='product:price:amount']"))
    tags = [
        tag.get_text(strip=True)
        for tag in soup.select('a[href*="/tags/"], a[href*="tags%5B"], a[href*="/ja/search/"]')
        if tag.get_text(strip=True)
    ]
    shop_link = soup.select_one('a[href*=".booth.pm"], a[href^="/shops/"]')
    page_text = soup.get_text(" ", strip=True)
    return ParsedItem(
        booth_item_id=booth_item_id(item_url),
        title=title[:300],
        item_url=item_url,
        image_url=absolute_url(str(image_value), item_url) if image_value else None,
        shop_name=shop_link.get_text(" ", strip=True)[:191] if shop_link else None,
        shop_url=absolute_url(shop_link.get("href"), item_url) if shop_link else None,
        description=description_value,
        price=price if price is not None else parse_price(page_text),
        tags=list(dict.fromkeys(tags))[:30],
        has_sale_label=("SALE" in page_text.upper() or "セール" in page_text),
    )


def summarize_parsed_items(items: list[ParsedItem]) -> dict:
    return {
        "count": len(items),
        "missing_price": sum(1 for item in items if item.price is None),
        "missing_image": sum(1 for item in items if not item.image_url),
        "missing_description": sum(1 for item in items if not item.description),
        "sample_titles": [item.title for item in items[:5]],
    }
