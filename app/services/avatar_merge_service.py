from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Avatar, AvatarAlias, ItemAvatarRelation, UserAvatarWatch
from app.services.avatar_service import ensure_alias


@dataclass
class DuplicateGroup:
    avatars: list[tuple[Avatar, int]]  # (avatar, item_count), sorted by item_count desc


def _normalized_terms(avatar: Avatar, alias_map: dict[int, list[str]]) -> set[str]:
    terms = {t.strip().casefold() for t in [avatar.name, avatar.reading or "", avatar.english_name or ""] if t and t.strip()}
    terms.update(t.strip().casefold() for t in alias_map.get(avatar.id, []) if t.strip())
    return terms


def find_duplicate_avatar_groups(db: Session) -> list[DuplicateGroup]:
    # Unlike base-body detection (which deliberately groups DIFFERENT avatars
    # that merely share a base body), this looks for avatars that are the
    # SAME character recorded twice. Only exact overlap of name/reading/
    # english_name/alias counts as a signal - no substring or fuzzy matching,
    # since that class of heuristic is exactly what caused false-positive
    # avatar matching earlier in this project.
    avatars = db.scalars(select(Avatar).where(Avatar.is_active.is_(True))).all()
    aliases = db.scalars(select(AvatarAlias)).all()
    alias_map: dict[int, list[str]] = {}
    for alias in aliases:
        alias_map.setdefault(alias.avatar_id, []).append(alias.alias)

    item_counts = dict(
        db.execute(
            select(ItemAvatarRelation.avatar_id, func.count(ItemAvatarRelation.item_id))
            .where(ItemAvatarRelation.match_type != "excluded")
            .group_by(ItemAvatarRelation.avatar_id)
        ).all()
    )

    # Union-find over avatars connected by any shared normalized term - if A
    # and B share a term, and B and C share a (possibly different) term,
    # they're overwhelmingly likely to all be the same character.
    parent: dict[int, int] = {avatar.id: avatar.id for avatar in avatars}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        root_x, root_y = find(x), find(y)
        if root_x != root_y:
            parent[root_y] = root_x

    term_to_avatar_ids: dict[str, list[int]] = {}
    for avatar in avatars:
        for term in _normalized_terms(avatar, alias_map):
            term_to_avatar_ids.setdefault(term, []).append(avatar.id)
    for avatar_ids in term_to_avatar_ids.values():
        for other_id in avatar_ids[1:]:
            union(avatar_ids[0], other_id)

    groups: dict[int, list[Avatar]] = {}
    for avatar in avatars:
        groups.setdefault(find(avatar.id), []).append(avatar)

    result = [
        DuplicateGroup(
            avatars=sorted(
                ((avatar, item_counts.get(avatar.id, 0)) for avatar in members),
                key=lambda pair: pair[1],
                reverse=True,
            )
        )
        for members in groups.values()
        if len(members) >= 2
    ]
    result.sort(key=lambda group: len(group.avatars), reverse=True)
    return result


def merge_avatars(db: Session, primary: Avatar, duplicates: list[Avatar]) -> int:
    repointed = 0
    for duplicate in duplicates:
        if duplicate.id == primary.id:
            continue
        for term in (duplicate.name, duplicate.reading or "", duplicate.english_name or ""):
            if term and term.strip():
                ensure_alias(db, primary, term.strip())
        for alias in db.scalars(select(AvatarAlias).where(AvatarAlias.avatar_id == duplicate.id)).all():
            ensure_alias(db, primary, alias.alias)

        for relation in db.scalars(select(ItemAvatarRelation).where(ItemAvatarRelation.avatar_id == duplicate.id)).all():
            existing = db.scalar(
                select(ItemAvatarRelation).where(
                    ItemAvatarRelation.item_id == relation.item_id,
                    ItemAvatarRelation.avatar_id == primary.id,
                )
            )
            if existing:
                db.delete(relation)
            else:
                relation.avatar_id = primary.id
                repointed += 1
        db.flush()

        for watch in db.scalars(select(UserAvatarWatch).where(UserAvatarWatch.avatar_id == duplicate.id)).all():
            existing_watch = db.scalar(
                select(UserAvatarWatch).where(
                    UserAvatarWatch.user_id == watch.user_id,
                    UserAvatarWatch.avatar_id == primary.id,
                )
            )
            if existing_watch:
                db.delete(watch)
            else:
                watch.avatar_id = primary.id
        db.flush()

        db.delete(duplicate)
        db.flush()
    db.commit()
    return repointed
