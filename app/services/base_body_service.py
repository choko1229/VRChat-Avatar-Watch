from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Avatar, BaseBody, ItemAvatarRelation, ItemTag
from app.services.detection import AvatarMatchIndex

# BOOTH tags that are generic marketplace/category labels rather than a
# specific base body's own brand name - treating these as a "shared tag"
# would lump together huge numbers of otherwise unrelated avatars, exactly
# the kind of over-eager grouping that made avatar matching unreliable
# before (see app/services/detection.py's isolated-mention rules).
_GENERIC_TAG_BLOCKLIST = {
    "3dモデル",
    "3dキャラクター",
    "vrchat",
    "vrc",
    "vrc想定モデル",
    "オリジナル3dモデル",
    "avatar",
    "無料",
    "セール",
    "3d衣装",
    "3d髪型",
    "3dツール・システム",
    "アバター",
    "衣装",
    "髪型",
    "アクセサリー",
    "小道具",
}
_MIN_TAG_LENGTH = 2
_MIN_SHARED_AVATARS = 2
_PURELY_NUMERIC = re.compile(r"^\d+$")
# BOOTH's own category-browse sidebar links get scraped as if they were
# per-item tags (see app/crawler/parser.py's tag extraction), showing up
# as e.g. "3D衣装(3575)" - a category label plus BOOTH's own item count
# for that category, not anything a seller attached to a specific item.
# These are the single biggest source of noise here: unlike real tags,
# they're identical across huge numbers of unrelated items/avatars.
_CATEGORY_COUNT_SUFFIX = re.compile(r"\(\d+\)$")


@dataclass
class BaseBodyCandidate:
    tag: str
    avatars: list[tuple[Avatar, int]]  # (avatar, item_count that supports this tag)


def detect_base_body_candidates(db: Session) -> list[BaseBodyCandidate]:
    # A single aggregate query, not a per-item Python loop - the reclassify
    # slowness earlier in this project came exactly from doing per-item work
    # across the whole catalog instead of letting the database aggregate.
    rows = db.execute(
        select(ItemTag.tag, ItemAvatarRelation.avatar_id, func.count(func.distinct(ItemTag.item_id)))
        .join(ItemAvatarRelation, ItemAvatarRelation.item_id == ItemTag.item_id)
        .where(ItemAvatarRelation.match_type != "excluded")
        .group_by(ItemTag.tag, ItemAvatarRelation.avatar_id)
    ).all()

    match_index = AvatarMatchIndex.build(db)
    avatars_by_id = {avatar.id: avatar for avatar in match_index.avatars if avatar.base_body_id is None}
    own_terms_by_id: dict[int, set[str]] = {}
    for avatar in avatars_by_id.values():
        terms = {t.strip().casefold() for t in [avatar.name, avatar.reading or "", avatar.english_name or ""] if t and t.strip()}
        terms.update(t.strip().casefold() for t in (avatar.search_keywords or "").split(",") if t.strip())
        terms.update(t.strip().casefold() for t in match_index.alias_map.get(avatar.id, []) if t.strip())
        own_terms_by_id[avatar.id] = terms

    grouped: dict[str, dict[int, int]] = {}
    for tag, avatar_id, item_count in rows:
        tag_norm = (tag or "").strip()
        tag_casefold = tag_norm.casefold()
        if (
            len(tag_norm) < _MIN_TAG_LENGTH
            or tag_casefold in _GENERIC_TAG_BLOCKLIST
            or _PURELY_NUMERIC.match(tag_norm)
            or _CATEGORY_COUNT_SUFFIX.search(tag_norm)
        ):
            continue
        avatar = avatars_by_id.get(avatar_id)
        if avatar is None:
            continue  # avatar not found, inactive, or already assigned a base body
        if tag_casefold in own_terms_by_id.get(avatar_id, set()):
            continue  # the avatar's own name/alias, not a shared base-body signal
        grouped.setdefault(tag_norm, {})[avatar_id] = item_count

    candidates = [
        BaseBodyCandidate(
            tag=tag,
            avatars=sorted(
                ((avatars_by_id[avatar_id], count) for avatar_id, count in avatar_counts.items()),
                key=lambda pair: pair[1],
                reverse=True,
            ),
        )
        for tag, avatar_counts in grouped.items()
        if len(avatar_counts) >= _MIN_SHARED_AVATARS
    ]
    candidates.sort(key=lambda c: (len(c.avatars), sum(count for _, count in c.avatars)), reverse=True)
    return candidates


def _slug_for_base_body(name: str) -> str:
    ascii_words = re.findall(r"[A-Za-z0-9]+", name)
    if ascii_words:
        return "-".join(word.casefold() for word in ascii_words)[:80] or "base-body"
    return "base-body"


def _unique_base_body_slug(db: Session, base_slug: str) -> str:
    slug = base_slug
    index = 2
    while db.scalar(select(BaseBody).where(BaseBody.slug == slug)):
        slug = f"{base_slug}-{index}"
        index += 1
    return slug


def apply_base_body_group(db: Session, name: str, avatar_ids: list[int]) -> BaseBody:
    base_body = db.scalar(select(BaseBody).where(BaseBody.name == name))
    if not base_body:
        base_body = BaseBody(name=name, slug=_unique_base_body_slug(db, _slug_for_base_body(name)))
        db.add(base_body)
        db.flush()
    avatars = db.scalars(select(Avatar).where(Avatar.id.in_(avatar_ids))).all()
    for avatar in avatars:
        avatar.base_body_id = base_body.id
    db.commit()
    return base_body


def remove_avatar_from_base_body(db: Session, avatar: Avatar) -> None:
    avatar.base_body_id = None
    db.commit()
