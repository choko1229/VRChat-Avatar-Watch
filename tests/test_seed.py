from sqlalchemy import select

from app.models import Avatar, AvatarAlias, CrawlTarget
from app.services.seed import DEFAULT_AVATARS, DEFAULT_CRAWL_TARGETS, seed_defaults


def test_default_avatar_aliases_do_not_duplicate_casefold_values():
    for avatar in DEFAULT_AVATARS:
        aliases = [alias.casefold() for alias in avatar["aliases"]]
        assert len(aliases) == len(set(aliases))


def test_seed_defaults_skips_existing_casefold_alias(db_session):
    avatar = Avatar(
        name="キプフェル",
        slug="kipfel",
        reading="きぷふぇる",
        english_name="Kipfel",
        search_keywords="キプフェル,Kipfel",
        exclude_keywords="",
    )
    db_session.add(avatar)
    db_session.flush()
    db_session.add(AvatarAlias(avatar_id=avatar.id, alias="KIPFEL"))
    db_session.commit()

    seed_defaults(db_session)

    aliases = set(db_session.scalars(select(AvatarAlias.alias).where(AvatarAlias.avatar_id == avatar.id)).all())
    assert aliases == {"KIPFEL", "キプフェル", "きぷふぇる"}


def test_seed_defaults_uses_broad_vrc_crawl_targets(db_session):
    db_session.add(CrawlTarget(target_type="keyword", target_value="キプフェル", is_active=True))
    db_session.add(CrawlTarget(target_type="avatar", target_value="キプフェル", is_active=True))
    db_session.commit()

    seed_defaults(db_session)

    broad_targets = {
        (target.target_type, target.target_value): target.is_active
        for target in db_session.scalars(select(CrawlTarget)).all()
        if (target.target_type, target.target_value) in DEFAULT_CRAWL_TARGETS
    }
    assert broad_targets == {target: True for target in DEFAULT_CRAWL_TARGETS}
    assert db_session.scalar(select(CrawlTarget).where(CrawlTarget.target_type == "keyword", CrawlTarget.target_value == "キプフェル")).is_active is False
    assert db_session.scalar(select(CrawlTarget).where(CrawlTarget.target_type == "avatar", CrawlTarget.target_value == "キプフェル")).is_active is False
