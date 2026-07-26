from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    inspect,
)

import app.database as database
from app import models  # noqa: F401 - registers models on database.Base.metadata


def _build_old_schema_missing_indexes(engine) -> None:
    # Mimics production before ItemTag.item_id / ItemAvatarRelation.item_id
    # and .avatar_id gained index=True: create_all() never alters an
    # existing table, so on a real deploy these tables exist without the new
    # indexes even after the model change ships.
    old_meta = MetaData()
    Table("items", old_meta, Column("id", Integer, primary_key=True))
    Table("avatars", old_meta, Column("id", Integer, primary_key=True))
    Table(
        "item_tags",
        old_meta,
        Column("id", Integer, primary_key=True),
        Column("item_id", Integer, ForeignKey("items.id")),
        Column("tag", String(191), index=True),
        Column("created_at", DateTime),
    )
    Table(
        "item_avatar_relations",
        old_meta,
        Column("id", Integer, primary_key=True),
        Column("item_id", Integer, ForeignKey("items.id")),
        Column("avatar_id", Integer, ForeignKey("avatars.id")),
        Column("match_type", String(20)),
        Column("match_reason", Text),
        Column("created_at", DateTime),
        Column("updated_at", DateTime),
        UniqueConstraint("item_id", "avatar_id", name="uq_item_avatar"),
    )
    old_meta.create_all(engine)


def test_ensure_missing_indexes_backfills_indexes_on_existing_table(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    _build_old_schema_missing_indexes(engine)

    before = {idx["name"] for idx in inspect(engine).get_indexes("item_tags")}
    assert "ix_item_tags_item_id" not in before

    monkeypatch.setattr(database, "engine", engine)
    database._ensure_missing_indexes()

    tag_indexes = {idx["name"] for idx in inspect(engine).get_indexes("item_tags")}
    relation_indexes = {idx["name"] for idx in inspect(engine).get_indexes("item_avatar_relations")}
    assert "ix_item_tags_item_id" in tag_indexes
    assert "ix_item_avatar_relations_item_id" in relation_indexes
    assert "ix_item_avatar_relations_avatar_id" in relation_indexes


def test_ensure_missing_indexes_is_idempotent(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    _build_old_schema_missing_indexes(engine)
    monkeypatch.setattr(database, "engine", engine)

    database._ensure_missing_indexes()
    database._ensure_missing_indexes()  # must not raise on the second call

    tag_indexes = {idx["name"] for idx in inspect(engine).get_indexes("item_tags")}
    assert "ix_item_tags_item_id" in tag_indexes


def test_ensure_missing_indexes_noop_on_freshly_created_schema(monkeypatch):
    # A brand-new install's create_all() already includes the indexes -
    # confirm the migration step doesn't error when there's nothing to do.
    engine = create_engine("sqlite:///:memory:")
    database.Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "engine", engine)

    database._ensure_missing_indexes()

    tag_indexes = {idx["name"] for idx in inspect(engine).get_indexes("item_tags")}
    assert "ix_item_tags_item_id" in tag_indexes
