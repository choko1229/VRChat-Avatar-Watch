from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import func, select
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
    "パーツ",
    "改変",
    "マテリアル",
    "キット",
    "プロファイル",
    "シェイプキー",
    "ノーマルマップ",
]
# A candidate extracted from the title with fewer than this many non-digit,
# non-punctuation characters is treated as a parsing artifact (e.g. a bare
# "7" or "300" left over from a version number or count in the title) rather
# than a real avatar name, and is rejected instead of becoming a new Avatar.
_MIN_MEANINGFUL_NAME_CHARS = 2
_DIGIT_AND_PUNCTUATION = re.compile(r"[\d\W_]", re.UNICODE)


def _haystack(item: Item, tags: list[str] | None = None) -> str:
    return " ".join([item.title or "", item.description or "", item.category or "", " ".join(tags or [])]).casefold()


def looks_like_avatar_product(item: Item, tags: list[str] | None = None) -> bool:
    full_text = _haystack(item, tags)
    if any(term.casefold() in full_text for term in AVATAR_NEGATIVE_TERMS):
        return False
    # Require the "this listing IS an avatar" signal to come from the title
    # or BOOTH's own category label, not a loose mention buried in the
    # description or tags - otherwise generic accessories/props/tools that
    # happen to reference "アバター" or get tagged under BOOTH's broad
    # "3Dモデル" category get mistaken for standalone avatars and spawn a
    # bogus Avatar entry (this was the main source of the false "対応アバター"
    # matches: those bogus entries had short, generic names that then
    # substring-matched unrelated items).
    title_and_category = " ".join([item.title or "", item.category or ""]).casefold()
    return any(term.casefold() in title_and_category for term in AVATAR_POSITIVE_TERMS)


def avatar_name_from_title(title: str) -> str | None:
    candidate = re.split(r"\s[/｜|／-]\s|[/｜|／]", title, maxsplit=1)[0]
    candidate = re.sub(r"【.*?】|\[.*?\]|\(.*?\)", "", candidate)
    candidate = re.sub(r"オリジナル3Dモデル|3Dモデル|VRChat|VRC|アバター|Avatar", "", candidate, flags=re.IGNORECASE)
    candidate = candidate.strip(" -_　[]【】()（）")
    if not candidate or len(candidate) > 80:
        return None
    meaningful_chars = _DIGIT_AND_PUNCTUATION.sub("", candidate)
    if len(meaningful_chars) < _MIN_MEANINGFUL_NAME_CHARS:
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


# Before avatar_name_from_title's own guards existed (min meaningful length,
# numeric rejection), titles that mention several different avatars in one
# listing (e.g. "うささき・キプフェル・まめひなた・アズキ専用...") or that BOOTH
# truncated with an ellipsis got parsed into a bogus "avatar" of their own.
# These are still sitting in the database as one-item entries that never
# match anything else - flag them for admin review rather than guessing at
# an automatic bulk delete, since a genuinely new/niche avatar can also
# legitimately have only its own listing so far.
_TRUNCATION_SUFFIXES = ("...", "…")
_LIST_SEPARATOR = "・"
_MIN_SEPARATORS_FOR_MASHUP = 2
# A production audit of the 0-1-item avatars turned up whole categories of
# non-character titles that got parsed into "avatars" the same way: props/
# poses/gimmicks whose own titles enumerate variations ("メガホン カラー11種",
# "撮影用ポーズセット03", "指輪 二種"), and creator/shop handles ("#MxU工房").
# A real character's own name essentially never contains these.
_VARIATION_COUNT_PATTERN = re.compile(r"[0-9〇一二三四五六七八九十]+[種色個点本]")
_NON_CHARACTER_PRODUCT_TERMS = ["ポーズ", "アニメーション", "ジェスチャー", "エフェクト", "想定"]
_SHOP_HANDLE_PREFIXES = ("#",)


def is_suspicious_avatar_name(name: str) -> bool:
    if name.endswith(_TRUNCATION_SUFFIXES):
        return True
    if name.count(_LIST_SEPARATOR) >= _MIN_SEPARATORS_FOR_MASHUP:
        return True
    if name.startswith(_SHOP_HANDLE_PREFIXES):
        return True
    # Same rule avatar_name_from_title() already applies at creation time -
    # a name that's mostly digits/punctuation (e.g. "06") is a parsing
    # artifact, not a usable name. Existing rows predate that guard.
    if len(_DIGIT_AND_PUNCTUATION.sub("", name)) < _MIN_MEANINGFUL_NAME_CHARS:
        return True
    if _VARIATION_COUNT_PATTERN.search(name):
        return True
    name_casefold = name.casefold()
    if any(term.casefold() in name_casefold for term in AVATAR_NEGATIVE_TERMS):
        return True
    return any(term.casefold() in name_casefold for term in _NON_CHARACTER_PRODUCT_TERMS)


@dataclass
class LowConfidenceAvatar:
    avatar: Avatar
    item_count: int
    suspicious: bool


def find_low_confidence_avatars(db: Session, max_item_count: int = 1) -> list[LowConfidenceAvatar]:
    item_counts = (
        select(ItemAvatarRelation.avatar_id, func.count(ItemAvatarRelation.item_id).label("item_count"))
        .where(ItemAvatarRelation.match_type != "excluded")
        .group_by(ItemAvatarRelation.avatar_id)
        .subquery()
    )
    rows = db.execute(
        select(Avatar, func.coalesce(item_counts.c.item_count, 0))
        .outerjoin(item_counts, item_counts.c.avatar_id == Avatar.id)
        .where(Avatar.is_active.is_(True))
    ).all()
    results = [
        LowConfidenceAvatar(avatar=avatar, item_count=count, suspicious=is_suspicious_avatar_name(avatar.name))
        for avatar, count in rows
        if count <= max_item_count
    ]
    results.sort(key=lambda r: (not r.suspicious, r.avatar.name))
    return results


def featured_avatars(db: Session, limit: int = 12) -> list[tuple[Avatar, int]]:
    item_counts = (
        select(ItemAvatarRelation.avatar_id, func.count(ItemAvatarRelation.item_id).label("item_count"))
        .where(ItemAvatarRelation.match_type != "excluded")
        .group_by(ItemAvatarRelation.avatar_id)
        .subquery()
    )
    return db.execute(
        select(Avatar, item_counts.c.item_count)
        .join(item_counts, item_counts.c.avatar_id == Avatar.id)
        .where(Avatar.is_active.is_(True))
        .order_by(item_counts.c.item_count.desc())
        .limit(limit)
    ).all()
