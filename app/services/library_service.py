from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawler.parser import parse_library_items
from app.models import Avatar, Item, ItemAvatarRelation, LibraryImportJob, User, UserOwnedItem
from app.services.detection import AvatarMatchIndex, detect_avatar_matches

# How often import_owned_items() commits a progress update to the job row -
# frequent enough that the live status modal (polled every 2s) feels
# responsive without committing on every single item.
_PROGRESS_BATCH = 10


def _report_progress(db: Session, job: LibraryImportJob | None, message: str) -> None:
    if job is None:
        return
    job.message = message
    db.commit()


def import_owned_items(db: Session, user: User, html: str, job: LibraryImportJob | None = None) -> dict:
    # Parses a pasted copy of BOOTH's own "ライブラリ" page (the user must be
    # logged into BOOTH themselves and copy the HTML - we never touch BOOTH
    # credentials or sessions). Upserts one UserOwnedItem per purchased item
    # and tries to recognize which of our known avatars it belongs to, so
    # related-item recommendations can be shown without any BOOTH access.
    parsed_items = parse_library_items(html)
    total = len(parsed_items)
    imported = 0
    matched = 0
    # Fetched once and reused for every item instead of re-querying every
    # avatar/alias per item - the N+1 pattern that made large libraries slow
    # enough to time out the request. Import never creates avatars, so no
    # mid-run invalidation is needed (unlike the crawler/reclassify).
    match_index = AvatarMatchIndex.build(db)
    _report_progress(db, job, f"0/{total} 件を解析中")
    for position, parsed in enumerate(parsed_items, start=1):
        owned = db.scalar(
            select(UserOwnedItem).where(
                UserOwnedItem.user_id == user.id,
                UserOwnedItem.booth_item_id == parsed.booth_item_id,
            )
        )
        if not owned:
            owned = UserOwnedItem(user_id=user.id, booth_item_id=parsed.booth_item_id, title=parsed.title, item_url=parsed.item_url)
            db.add(owned)
            imported += 1
        owned.title = parsed.title
        owned.item_url = parsed.item_url
        owned.image_url = parsed.image_url
        owned.shop_name = parsed.shop_name
        owned.shop_url = parsed.shop_url
        if owned.avatar_id is None:
            matches = detect_avatar_matches(db, parsed.title, None, [], index=match_index)
            if matches:
                owned.avatar_id = matches[0][0].id
                matched += 1
        if position % _PROGRESS_BATCH == 0 or position == total:
            _report_progress(db, job, f"{position}/{total} 件を取り込み中(新規{imported}件・アバター認識{matched}件)")
    db.commit()
    return {"parsed": total, "imported": imported, "matched": matched}


def owned_items_for_user(db: Session, user: User) -> list[UserOwnedItem]:
    return db.scalars(
        select(UserOwnedItem).where(UserOwnedItem.user_id == user.id).order_by(UserOwnedItem.created_at.desc())
    ).all()


def related_items_for_owned_avatars(db: Session, user: User, limit_per_avatar: int = 6) -> list[tuple[Avatar, list[Item]]]:
    owned_avatar_ids = [
        avatar_id
        for avatar_id in db.scalars(
            select(UserOwnedItem.avatar_id).where(UserOwnedItem.user_id == user.id, UserOwnedItem.avatar_id.is_not(None)).distinct()
        ).all()
    ]
    if not owned_avatar_ids:
        return []
    owned_booth_ids = set(db.scalars(select(UserOwnedItem.booth_item_id).where(UserOwnedItem.user_id == user.id)).all())
    avatars = db.scalars(select(Avatar).where(Avatar.id.in_(owned_avatar_ids)).order_by(Avatar.name)).all()
    results: list[tuple[Avatar, list[Item]]] = []
    for avatar in avatars:
        candidates = db.scalars(
            select(Item)
            .join(ItemAvatarRelation, ItemAvatarRelation.item_id == Item.id)
            .where(ItemAvatarRelation.avatar_id == avatar.id)
            .order_by(Item.created_at.desc())
            .limit(limit_per_avatar + 20)
        ).all()
        filtered = [item for item in candidates if item.booth_item_id not in owned_booth_ids][:limit_per_avatar]
        if filtered:
            results.append((avatar, filtered))
    return results
