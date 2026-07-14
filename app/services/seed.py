from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Avatar, AvatarAlias, CrawlTarget, Setting, Tool


DEFAULT_AVATARS = [
    {
        "name": "キプフェル",
        "slug": "kipfel",
        "reading": "きぷふぇる",
        "english_name": "Kipfel",
        "aliases": ["キプフェル", "Kipfel", "きぷふぇる"],
        "keywords": "キプフェル,Kipfel,きぷふぇる",
    },
    {
        "name": "まめひなた",
        "slug": "mamehinata",
        "reading": "まめひなた",
        "english_name": "Mamehinata",
        "aliases": ["まめひなた", "Mamehinata"],
        "keywords": "まめひなた,Mamehinata",
    },
    {
        "name": "みるてぃな",
        "slug": "miltina",
        "reading": "みるてぃな",
        "english_name": "Miltina",
        "aliases": ["みるてぃな", "Miltina"],
        "keywords": "みるてぃな,Miltina",
    },
    {
        "name": "ネメシス",
        "slug": "nemesis",
        "reading": "ねめしす",
        "english_name": "Nemesis",
        "aliases": ["ネメシス", "Nemesis"],
        "keywords": "ネメシス,Nemesis",
    },
]

DEFAULT_TOOLS = [
    ("lilToon", "liltoon", "VRChat向けシェーダー", "lilToon,liltoon"),
    ("Modular Avatar", "modular-avatar", "非破壊アバター改変ツール", "Modular Avatar,ModularAvatar"),
    ("VRCFury", "vrcfury", "VRChatアバターセットアップ補助", "VRCFury,VRC Fury"),
    ("Avatar Optimizer", "avatar-optimizer", "アバター最適化ツール", "Avatar Optimizer,AAO"),
]

DEFAULT_CRAWL_TARGETS = [
    ("keyword", "VRChat"),
    ("keyword", "VRC"),
]

DEFAULT_SETTINGS = {
    "crawl_interval_hours": ("6", False),
    "crawl_concurrency": ("1", False),
    "min_crawl_interval_minutes": ("30", False),
    "max_search_pages_per_crawl": ("5", False),
    "max_detail_pages_per_crawl": ("20", False),
    "crawl_request_interval_ms": ("1000", False),
    "thumbnail_cache_days": ("30", False),
    "thumbnail_cache_max_gb": ("10", False),
    "site_name": ("VRChat Avatar Watch", False),
    "misskey_instance_url": ("", False),
    "misskey_token": ("", True),
    "discord_webhook_admin": ("", True),
    "discord_webhook_public": ("", True),
    "discord_client_id": ("", False),
    "discord_client_secret": ("", True),
    "discord_redirect_uri": ("", False),
}


def seed_defaults(db: Session) -> None:
    for key, (value, is_secret) in DEFAULT_SETTINGS.items():
        if not db.scalar(select(Setting).where(Setting.key == key)):
            db.add(Setting(key=key, value=value, is_secret=is_secret))

    default_avatar_keywords: set[str] = set()
    for data in DEFAULT_AVATARS:
        avatar = db.scalar(select(Avatar).where(Avatar.slug == data["slug"]))
        if not avatar:
            avatar = Avatar(
                name=data["name"],
                slug=data["slug"],
                reading=data["reading"],
                english_name=data["english_name"],
                search_keywords=data["keywords"],
                exclude_keywords="",
            )
            db.add(avatar)
            db.flush()
        existing_aliases = {
            alias.casefold()
            for alias in db.scalars(select(AvatarAlias.alias).where(AvatarAlias.avatar_id == avatar.id)).all()
        }
        for alias in data["aliases"]:
            normalized_alias = alias.casefold()
            if normalized_alias not in existing_aliases:
                db.add(AvatarAlias(avatar_id=avatar.id, alias=alias))
                existing_aliases.add(normalized_alias)
        for keyword in data["keywords"].split(","):
            default_avatar_keywords.add(keyword)

    for target_type, target_value in DEFAULT_CRAWL_TARGETS:
        target = db.scalar(select(CrawlTarget).where(CrawlTarget.target_type == target_type, CrawlTarget.target_value == target_value))
        if not target:
            db.add(CrawlTarget(target_type=target_type, target_value=target_value))
        else:
            target.is_active = True

    for target in db.scalars(select(CrawlTarget).where(CrawlTarget.target_type.in_(["avatar", "keyword"]))).all():
        if target.target_type == "avatar" or target.target_value in default_avatar_keywords:
            target.is_active = False

    for name, slug, description, keywords in DEFAULT_TOOLS:
        if not db.scalar(select(Tool).where(Tool.slug == slug)):
            db.add(Tool(name=name, slug=slug, description=description, search_keywords=keywords, exclude_keywords=""))
    db.commit()
