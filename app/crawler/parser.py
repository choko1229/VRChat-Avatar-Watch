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


def _background_image_url(style: str | None) -> str | None:
    if not style:
        return None
    match = re.search(r"background-image:\s*url\((['\"]?)(.*?)\1\)", style)
    return match.group(2) if match else None


def _node_image_url(node, base_url: str) -> str | None:
    image = node.select_one("[data-original], img[src], img[data-src]")
    if not image:
        return None
    value = image.get("data-original") or image.get("src") or image.get("data-src") or _background_image_url(image.get("style"))
    return absolute_url(value, base_url)


def _offer_price(offers: dict) -> int | None:
    for key in ("price", "lowPrice", "highPrice"):
        if offers.get(key) is not None:
            price = parse_price(str(offers.get(key)))
            if price is not None:
                return price
    return None


def _detail_dom_price(soup: BeautifulSoup) -> int | None:
    market = soup.select_one(".market[data-product-price], [data-shop-tracking-product-price]")
    if market:
        price = parse_price(market.get("data-product-price") or market.get("data-shop-tracking-product-price"))
        if price is not None:
            return price
    prices = [parse_price(node.get_text(" ", strip=True)) for node in soup.select(".variation-price, .price")]
    prices = [price for price in prices if price is not None]
    return min(prices) if prices else None


def parse_variations(soup: BeautifulSoup) -> list[tuple[str, int | None]]:
    # BOOTH items can offer several separately-purchasable options (e.g. a
    # normal edition, a deluxe edition, plus a free bonus/config file). Each
    # shows up as its own ".variation-item" with a name and price.
    variations: list[tuple[str, int | None]] = []
    for node in soup.select(".variation-item"):
        name_node = node.select_one(".variation-name")
        price_node = node.select_one(".variation-price")
        name = name_node.get_text(" ", strip=True) if name_node else ""
        if not name:
            continue
        price = parse_price(price_node.get_text(" ", strip=True)) if price_node else None
        variations.append((name, price))
    return variations


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
    for card in soup.select("li.item-card"):
        product_id = card.get("data-product-id")
        link = card.select_one('a[href*="/items/"]')
        href = link.get("href") if link else ""
        url = absolute_url(href, base_url) or (f"{base_url.rstrip('/')}/ja/items/{product_id}" if product_id else "")
        title_node = card.select_one(".item-card__title a")
        title = card.get("data-product-name") or (title_node.get_text(" ", strip=True) if title_node else "")
        if not title or not url:
            continue
        shop_link = card.select_one(".item-card__shop-name-anchor")
        shop_name_node = card.select_one(".item-card__shop-name")
        category_node = card.select_one(".item-card__category-anchor")
        price_node = card.select_one(".price")
        price_text = card.get("data-product-price") or (price_node.get_text(" ", strip=True) if price_node else "")
        card_text = card.get_text(" ", strip=True)
        parsed = ParsedItem(
            booth_item_id=product_id or booth_item_id(url),
            title=title[:300],
            item_url=url,
            image_url=_node_image_url(card, base_url),
            shop_name=shop_name_node.get_text(" ", strip=True)[:191] if shop_name_node else None,
            shop_url=absolute_url(shop_link.get("href"), base_url) if shop_link else None,
            price=parse_price(price_text),
            tags=[
                image.get("alt", "").strip()
                for image in card.select(".l-item-card-badge img[alt]")
                if image.get("alt", "").strip()
            ],
            category=category_node.get_text(" ", strip=True) if category_node else None,
            has_sale_label=("SALE" in card_text.upper() or "セール" in card_text),
        )
        if parsed.booth_item_id and all(existing.booth_item_id != parsed.booth_item_id for existing in items):
            items.append(parsed)
    if items:
        return items

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
            image_url=_node_image_url(card, base_url) or absolute_url((img.get("src") or img.get("data-src")) if img else None, base_url),
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
    variations = parse_variations(soup)
    paid_variation_prices = [p for _, p in variations if p]
    if variations:
        # A multi-variation item's JSON-LD "offers" is often an
        # AggregateOffer whose lowPrice is 0 because a free bonus/config
        # file is included as one of the options - that would make a
        # paid item look free. Prefer the cheapest *paid* option instead;
        # only treat the item as free if every option is actually free.
        price = min(paid_variation_prices) if paid_variation_prices else 0
    else:
        offers = product.get("offers") if isinstance(product.get("offers"), dict) else {}
        price = _offer_price(offers)
        if price is None:
            price = parse_price(_meta_content(soup, "meta[property='product:price:amount']"))
        if price is None:
            price = _detail_dom_price(soup)
    if len(variations) > 1:
        options_text = "\n".join(f"- {name}: {'¥' + format(p, ',') if p else '無料'}" for name, p in variations)
        description_value = f"{description_value or ''}\n\n【購入オプション】\n{options_text}".strip()
    tags = [
        tag.get_text(strip=True)
        for tag in soup.select('a[href*="/tags/"], a[href*="tags%5B"], a[href*="/ja/search/"]')
        if tag.get_text(strip=True)
    ]
    tags.extend(
        image.get("alt", "").strip()
        for image in soup.select('a[href*="tags%5B"] img[alt]')
        if image.get("alt", "").strip()
    )
    shop_link = soup.select_one('a[href*=".booth.pm"], a[href^="/shops/"]')
    brand = product.get("brand") if isinstance(product.get("brand"), dict) else {}
    page_text = soup.get_text(" ", strip=True)
    return ParsedItem(
        booth_item_id=booth_item_id(item_url),
        title=title[:300],
        item_url=item_url,
        image_url=absolute_url(str(image_value), item_url) if image_value else None,
        shop_name=(brand.get("name") or (shop_link.get_text(" ", strip=True) if shop_link else None) or "")[:191] or None,
        shop_url=absolute_url(brand.get("url") or (shop_link.get("href") if shop_link else None), item_url),
        description=description_value,
        price=price,
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
