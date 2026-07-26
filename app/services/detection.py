from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Avatar, AvatarAlias, CrawlLog, Item, ItemAvatarRelation, ItemTag, Tool
from app.services.avatar_service import ensure_avatar_page_for_item, has_pending_or_saved_avatar_relation

# How often reclassify_all_items() commits a progress update while working
# through potentially thousands of items - frequent enough that the live
# status panel (polled every 2s) feels responsive, without committing on
# every single item.
_RECLASSIFY_PROGRESS_BATCH = 25


NSFW_PATTERNS = [r"R-?18", r"NSFW", "成人向け", "18禁"]
NSFW_NEGATION_PATTERNS = [r"R-?18\s*(ではない|ではありません|なし|無し|非対応|不要)", r"NSFW\s*(ではない|なし|無し)"]

# Characters that count as "part of a word" for the purposes of avatar-name
# matching: ASCII alnum, hiragana, katakana (+長音符), kanji. A candidate is
# only considered a real mention if it isn't glued directly onto more of
# these characters on either side - e.g. "ネコ" must not match inside
# "ネコチヤン", a different avatar's name.
_CJK_WORD_CHARS = "0-9A-Za-zぁ-んァ-ヶー一-龯"
# Common BOOTH title suffixes that legitimately follow an avatar name with no
# delimiter in between (e.g. "キプフェル専用", "キプフェル対応"). Without this,
# the boundary rule above would reject these very common, very real mentions.
_AVATAR_NAME_SUFFIXES = ("専用", "対応", "向け", "仕様", "様", "用")
_MIN_AVATAR_CANDIDATE_LENGTH = 2
# A candidate that is nothing but digits (e.g. "32", "278") is essentially
# never a real, distinguishing avatar name or keyword on its own - those
# numbers show up constantly and innocuously as version numbers, avatar
# counts ("20アバター対応"), dates, and prices. Some avatars created before
# the creation-side guard existed ended up with bare-number names (a title
# like "《278》..." losing its brackets during parsing), and those numbers
# then isolated-mention-matched all sorts of unrelated items. Reject them
# here too so already-existing bad data can't match anything even before
# it's cleaned up via /admin/avatars.
_PURELY_NUMERIC = re.compile(r"^\d+$")


def _is_isolated_mention(candidate: str, text: str) -> bool:
    if not candidate or len(candidate) < _MIN_AVATAR_CANDIDATE_LENGTH or not text:
        return False
    if _PURELY_NUMERIC.match(candidate):
        return False
    suffix_alternation = "|".join(re.escape(suffix) for suffix in _AVATAR_NAME_SUFFIXES)
    pattern = re.compile(
        rf"(?<![{_CJK_WORD_CHARS}]){re.escape(candidate)}(?:$|[^{_CJK_WORD_CHARS}]|{suffix_alternation})"
    )
    return pattern.search(text) is not None


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


@dataclass
class AvatarMatchIndex:
    # Bundles the avatar/alias lookup data detect_avatar_matches() needs so
    # a caller processing many items in one batch (a crawl page, a bulk
    # reclassify, a library import) can fetch it ONCE and reuse it, instead
    # of re-querying every avatar and every alias from the DB for every
    # single item - the N+1 pattern that made those bulk operations slow
    # enough to time out.
    avatars: list[Avatar]
    alias_map: dict[int, list[str]]

    @classmethod
    def build(cls, db: Session) -> "AvatarMatchIndex":
        avatars = db.scalars(select(Avatar).where(Avatar.is_active.is_(True))).all()
        aliases = db.scalars(select(AvatarAlias)).all()
        alias_map: dict[int, list[str]] = {}
        for alias in aliases:
            alias_map.setdefault(alias.avatar_id, []).append(alias.alias)
        return cls(avatars=avatars, alias_map=alias_map)

    def has_avatar(self, avatar_id: int) -> bool:
        return any(a.id == avatar_id for a in self.avatars)


def detect_avatar_matches(
    db: Session,
    title: str,
    description: str | None,
    tags: list[str] | None = None,
    index: AvatarMatchIndex | None = None,
) -> list[tuple[Avatar, str]]:
    # Tags are curated, discrete labels a seller chose deliberately, so an
    # exact/isolated tag mention is the strongest signal. Title mentions are
    # next-strongest (BOOTH titles conventionally call out compatible avatars
    # with brackets/suffixes like "【キプフェル対応】"). Description text is the
    # weakest signal - it's free-form prose most likely to contain an
    # unrelated, coincidental mention - so it's tried last.
    fields = (
        ("tag", " / ".join(tags or []).casefold()),
        ("title", (title or "").casefold()),
        ("description", (description or "").casefold()),
    )
    exclude_text = " ".join(text for _, text in fields)
    matches: list[tuple[Avatar, str]] = []
    match_index = index or AvatarMatchIndex.build(db)

    for avatar in match_index.avatars:
        exclude = [word.strip().casefold() for word in (avatar.exclude_keywords or "").split(",") if word.strip()]
        if any(word in exclude_text for word in exclude):
            continue
        candidates = [c.strip() for c in [avatar.name, avatar.reading or "", avatar.english_name or ""] if c and c.strip()]
        candidates.extend(c.strip() for c in (avatar.search_keywords or "").split(",") if c.strip())
        candidates.extend(c.strip() for c in match_index.alias_map.get(avatar.id, []) if c.strip())

        match: tuple[str, str] | None = None
        for field_name, field_text in fields:
            for candidate in candidates:
                if _is_isolated_mention(candidate.casefold(), field_text):
                    match = (field_name, candidate)
                    break
            if match:
                break
        if match:
            matches.append((avatar, f"{match[0]}:{match[1]}"))
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


def apply_avatar_matches(db: Session, item: Item, tags: list[str] | None = None, index: AvatarMatchIndex | None = None) -> None:
    for avatar, reason in detect_avatar_matches(db, item.title, item.description, tags, index=index):
        if not has_pending_or_saved_avatar_relation(db, item.id, avatar.id):
            db.add(ItemAvatarRelation(item_id=item.id, avatar_id=avatar.id, match_type="auto", match_reason=reason))


def _report_reclassify_progress(db: Session, log: CrawlLog | None, message: str, item_count: int | None = None) -> None:
    if log is None:
        return
    log.message = message
    if item_count is not None:
        log.item_count = item_count
    db.commit()


def reclassify_all_items(db: Session, log: CrawlLog | None = None) -> dict[str, int]:
    # Re-runs avatar auto-creation and matching against every item already in
    # the DB using the current rules, without touching BOOTH. Only "auto"
    # relations are dropped and recreated from scratch - relations an admin
    # set manually (match_type "manual"/"excluded") are left alone.
    items = db.scalars(select(Item)).all()
    total = len(items)
    relations_removed = 0
    relations_added = 0
    avatars_touched = 0
    match_index = AvatarMatchIndex.build(db)
    _report_reclassify_progress(db, log, f"0/{total} 件を再判定中", 0)
    for position, item in enumerate(items, start=1):
        tags = [
            tag for tag in db.scalars(select(ItemTag.tag).where(ItemTag.item_id == item.id)).all() if tag
        ]
        stale_relations = db.scalars(
            select(ItemAvatarRelation).where(
                ItemAvatarRelation.item_id == item.id,
                ItemAvatarRelation.match_type == "auto",
            )
        ).all()
        for relation in stale_relations:
            db.delete(relation)
            relations_removed += 1
        db.flush()
        touched_avatar = ensure_avatar_page_for_item(db, item, tags)
        if touched_avatar is not None:
            avatars_touched += 1
            if not match_index.has_avatar(touched_avatar.id):
                # A brand-new avatar was just created from this item - refresh
                # the cached index so later items in this same run can still
                # match against it.
                match_index = AvatarMatchIndex.build(db)
        before = db.scalar(
            select(func.count()).select_from(ItemAvatarRelation).where(ItemAvatarRelation.item_id == item.id)
        )
        apply_avatar_matches(db, item, tags, index=match_index)
        after = db.scalar(
            select(func.count()).select_from(ItemAvatarRelation).where(ItemAvatarRelation.item_id == item.id)
        )
        relations_added += max(0, (after or 0) - (before or 0))
        if position % _RECLASSIFY_PROGRESS_BATCH == 0 or position == total:
            _report_reclassify_progress(
                db,
                log,
                f"{position}/{total} 件を再判定中(削除{relations_removed}件・追加{relations_added}件)",
                position,
            )
    db.commit()
    return {
        "items": total,
        "relations_removed": relations_removed,
        "relations_added": relations_added,
        "avatars_touched": avatars_touched,
    }
