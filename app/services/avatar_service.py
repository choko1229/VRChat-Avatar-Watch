from __future__ import annotations

import re
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Avatar, AvatarAlias, Item, ItemAvatarRelation

AVATAR_POSITIVE_TERMS = [
    "オリジナル3Dモデル",
    "3Dモデル",
    "3Dキャラクター",
    "アバター",
    "avatar",
]
AVATAR_NEGATIVE_TERMS = [
    "対応",
    "衣装",
    "服",
    "ギミック",
    "ツール",
    "アクセ",
    "髪型",
    "テクスチャ",
    "texture",
    "shader",
]


def _haystack(item: Item, tags: list[str] | None = None) -> str:
    return " ".join([item.title or "", item.description or "", item.category or "", " ".join(tags or [])]).casefold()


def looks_like_avatar_product(item: Item, tags: list[str] | None = None) -> bool:
    text = _haystack(item, tags)
    if any(term.casefold() in text for term in AVATAR_NEGATIVE_TERMS):
        return False
    return any(term.casefold() in text for term in AVATAR_POSITIVE_TERMS)


def avatar_name_from_title(title: str) -> str | None:
    candidate = re.split(r"\s[/｜|／-]\s|[/｜|／]", title, maxsplit=1)[0]
    candidate = re.sub(r"【.*?】|\[.*?\]|\(.*?\)", "", candidate)
    candidate = re.sub(r"オリジナル3Dモデル|3Dモデル|VRChat|VRC|アバター|Avatar", "", candidate, flags=re.IGNORECASE)
    candidate = candidate.strip(" -_　[]【】()（）")
    if not candidate or len(candidate) > 80:
        return None
    return candidate


def slug_from_name(name: str, item_url: str) -> str:
    ascii_words = re.findall(r"[A-Za-z0-9]+", name)
    if ascii_words:
        slug = "-".join(word.casefold() for word in ascii_words)[:80]
    else:
        match = re.search(r"/items/(\d+)", item_url)
        slug = f"avatar-{match.group(1)}" if match else "avatar"
    return slug.strip("-") or "avatar"


def unique_slug(db: Session, base_slug: str) -> str:
    slug = base_slug
    index = 2
    while db.scalar(select(Avatar).where(Avatar.slug == slug)):
        slug = f"{base_slug}-{index}"
        index += 1
    return slug


def ensure_alias(db: Session, avatar: Avatar, alias: str) -> None:
    alias = alias.strip()
    if not alias:
        return
    exists = db.scalar(select(AvatarAlias).where(AvatarAlias.avatar_id == avatar.id, AvatarAlias.alias == alias))
    if not exists:
        db.add(AvatarAlias(avatar_id=avatar.id, alias=alias))


def has_pending_or_saved_avatar_relation(db: Session, item_id: int, avatar_id: int) -> bool:
    for pending in db.new:
        if (
            isinstance(pending, ItemAvatarRelation)
            and pending.item_id == item_id
            and pending.avatar_id == avatar_id
        ):
            return True
    return bool(
        db.scalar(
            select(ItemAvatarRelation).where(
                ItemAvatarRelation.item_id == item_id,
                ItemAvatarRelation.avatar_id == avatar_id,
            )
        )
    )


def ensure_avatar_page_for_item(db: Session, item: Item, tags: list[str] | None = None) -> Avatar | None:
    if not looks_like_avatar_product(item, tags):
        return None
    name = avatar_name_from_title(item.title)
    if not name:
        return None
    avatar = db.scalar(select(Avatar).where(Avatar.name == name))
    if not avatar:
        avatar = Avatar(
            name=name,
            slug=unique_slug(db, slug_from_name(name, item.item_url)),
            booth_url=item.item_url,
            image_url=item.image_url,
            search_keywords=name,
            exclude_keywords="",
            is_active=True,
        )
        db.add(avatar)
        db.flush()
    else:
        avatar.booth_url = avatar.booth_url or item.item_url
        avatar.image_url = avatar.image_url or item.image_url
        avatar.search_keywords = avatar.search_keywords or name
    ensure_alias(db, avatar, name)
    parsed = urlparse(item.item_url)
    if parsed.path:
        ensure_alias(db, avatar, parsed.path.rsplit("/", 1)[-1])
    if not has_pending_or_saved_avatar_relation(db, item.id, avatar.id):
        db.add(ItemAvatarRelation(item_id=item.id, avatar_id=avatar.id, match_type="auto", match_reason="avatar_product"))
    return avatar
