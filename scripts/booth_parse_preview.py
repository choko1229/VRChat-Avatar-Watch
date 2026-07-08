from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bs4 import BeautifulSoup

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app.crawler.parser import parse_item_detail, parse_search_results, summarize_parsed_items


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview BOOTH parser output from a saved HTML file.")
    parser.add_argument("html_file")
    parser.add_argument("--type", choices=["search", "detail"], default="search")
    parser.add_argument("--url", default="https://booth.pm")
    parser.add_argument("--debug-item-id")
    args = parser.parse_args()

    html = Path(args.html_file).read_text(encoding="utf-8")
    if args.debug_item_id:
        soup = BeautifulSoup(html, "html.parser")
        link = soup.find("a", href=lambda href: href and f"/items/{args.debug_item_id}" in href)
        node = link
        for depth in range(8):
            if not node:
                break
            print(f"up {depth}: {node.name} class={node.get('class')}")
            print(str(node)[:900].replace("\n", " "))
            node = node.parent
        return

    items = parse_search_results(html, args.url) if args.type == "search" else [parse_item_detail(html, args.url)]
    print(json.dumps(summarize_parsed_items(items), ensure_ascii=False, indent=2))
    for index, item in enumerate(items[:10], start=1):
        print(
            json.dumps(
                {
                    "index": index,
                    "booth_item_id": item.booth_item_id,
                    "title": item.title,
                    "price": item.price,
                    "item_url": item.item_url,
                    "has_image": bool(item.image_url),
                    "shop_name": item.shop_name,
                    "tags": item.tags[:8],
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
