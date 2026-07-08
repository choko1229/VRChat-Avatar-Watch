from sqlalchemy import select

from app.models import Avatar, AvatarAlias
from app.services.seed import DEFAULT_AVATARS, seed_defaults


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
