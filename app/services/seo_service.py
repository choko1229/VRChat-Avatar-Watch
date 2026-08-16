from __future__ import annotations

from fastapi import Request

from app.config import get_config
from app.models import Avatar, BaseBody, Item
from app.templating import canonical_url


def _site_origin(request: Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}"


def _breadcrumb(request: Request, *crumbs: tuple[str, str]) -> dict:
    site_name = get_config().site_name
    origin = _site_origin(request)
    items = [{"@type": "ListItem", "position": 1, "name": site_name, "item": f"{origin}/"}]
    for position, (name, path) in enumerate(crumbs, start=2):
        url = path if path.startswith("http") else f"{origin}{path}"
        items.append({"@type": "ListItem", "position": position, "name": name, "item": url})
    return {"@type": "BreadcrumbList", "itemListElement": items}


def product_json_ld(request: Request, item: Item) -> dict:
    # aggregateRating is deliberately omitted - we don't have review data,
    # and a fabricated rating risks a Google Merchant/rich-result penalty.
    canonical = canonical_url(request)
    product: dict = {
        "@type": "Product",
        "name": item.title,
        "description": (item.description or item.title)[:500],
        "url": canonical,
    }
    image = item.thumbnail_cache_path or item.image_url
    if image:
        product["image"] = image
    product["offers"] = {
        "@type": "Offer",
        "price": str(item.current_price) if item.current_price is not None else "0",
        "priceCurrency": "JPY",
        "availability": "https://schema.org/InStock",
        "url": item.item_url,
    }
    return {"@context": "https://schema.org", "@graph": [product, _breadcrumb(request, (item.title, canonical))]}


def avatar_json_ld(request: Request, avatar: Avatar) -> dict:
    canonical = canonical_url(request)
    return {"@context": "https://schema.org", "@graph": [_breadcrumb(request, ("アバター一覧", "/avatars"), (avatar.name, canonical))]}


def base_body_json_ld(request: Request, base_body: BaseBody) -> dict:
    canonical = canonical_url(request)
    return {"@context": "https://schema.org", "@graph": [_breadcrumb(request, ("素体一覧", "/base-bodies"), (base_body.name, canonical))]}
