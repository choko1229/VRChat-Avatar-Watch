from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Avatar, AvatarAlias, Item, ItemAvatarRelation, Tool


NSFW_PATTERNS = [r"R-?18", r"NSFW", "成人向け", "18禁"]
NSFW_NEGATION_PATTERNS = [r"R-?18\s*(ではない|ではありません|なし|無し|非対応|不要)", r"NSFW\s*(ではない|なし|無し)"]


@dataclass
class PriceDecision:
    is_free: bool
    is_on_sale: bool
    discount_rate: int
    reason: str


def _haystack(title: str | None, description: str | None, tags: list[str] | None) -> str:
    return " ".join([title or "", description or "", " ".join(tags or [])]).casefold()


def detect_nsfw(title: str | None, description: str | None, tags: list[str] | None = None) -> bool:
    text = _haystack(title, description, tags)
    if any(re.search(pattern.casefold(), text, re.IGNORECASE) for pattern in NSFW_NEGATION_PATTERNS):
        return False
    return any(re.search(pattern.casefold(), text, re.IGNORECASE) for pattern in NSFW_PATTERNS)


def detect_free(title: str | None, description: str | None, price: int | None) -> bool:
    text = _haystack(title, description, [])
    return price == 0 or "無料" in text or "無料配布" in text or "期間限定無料" in text


def detect_sale(current_price: int | None, previous_price: int | None, lowest_price: int | None, has_booth_sale_label: bool = False) -> PriceDecision:
    if current_price is None:
        return PriceDecision(False, False, 0, "price_missing")
    reference = previous_price if previous_price is not None else lowest_price
    if has_booth_sale_label and reference and current_price < reference:
        rate = round((reference - current_price) / reference * 100)
        return PriceDecision(current_price == 0, True, rate, "booth_sale_label")
    if reference and current_price < reference:
        rate = round((reference - current_price) / reference * 100)
        return PriceDecision(current_price == 0, True, rate, "price_drop")
    return PriceDecision(current_price == 0, False, 0, "normal")


def detect_avatar_matches(db: Session, title: str, description: str | None, tags: list[str] | None = None) -> list[tuple[Avatar, str]]:
    text = _haystack(title, description, tags)
    matches: list[tuple[Avatar, str]] = []
    avatars = db.scalars(select(Avatar).where(Avatar.is_active.is_(True))).all()
    aliases = db.scalars(select(AvatarAlias)).all()
    alias_map: dict[int, list[str]] = {}
    for alias in aliases:
        alias_map.setdefault(alias.avatar_id, []).append(alias.alias)

    for avatar in avatars:
        exclude = [word.strip().casefold() for word in (avatar.exclude_keywords or "").split(",") if word.strip()]
        if any(word in text for word in exclude):
            continue
        candidates = [avatar.name, avatar.reading or "", avatar.english_name or ""]
        candidates.extend((avatar.search_keywords or "").split(","))
        candidates.extend(alias_map.get(avatar.id, []))
        for candidate in candidates:
            normalized = candidate.strip().casefold()
            if normalized and normalized in text:
                matches.append((avatar, f"keyword:{candidate.strip()}"))
                break
    return matches


def detect_tool(db: Session, title: str, description: str | None, tags: list[str] | None = None) -> bool:
    text = _haystack(title, description, tags)
    tools = db.scalars(select(Tool).where(Tool.is_active.is_(True))).all()
    for tool in tools:
        exclude = [word.strip().casefold() for word in (tool.exclude_keywords or "").split(",") if word.strip()]
        if any(word in text for word in exclude):
            continue
        terms = [tool.name, *(tool.search_keywords or "").split(",")]
        if any(term.strip().casefold() in text for term in terms if term.strip()):
            return True
    return False


def apply_avatar_matches(db: Session, item: Item, tags: list[str] | None = None) -> None:
    for avatar, reason in detect_avatar_matches(db, item.title, item.description, tags):
        existing = db.scalar(
            select(ItemAvatarRelation).where(
                ItemAvatarRelation.item_id == item.id,
                ItemAvatarRelation.avatar_id == avatar.id,
            )
        )
        if not existing:
            db.add(ItemAvatarRelation(item_id=item.id, avatar_id=avatar.id, match_type="auto", match_reason=reason))
