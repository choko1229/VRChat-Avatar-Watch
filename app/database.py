from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_config


class Base(DeclarativeBase):
    pass


def _engine():
    config = get_config()
    kwargs = {"pool_pre_ping": True}
    if config.database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(config.database_url, **kwargs)


engine = _engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def refresh_engine() -> None:
    global engine, SessionLocal
    engine.dispose()
    engine = _engine()
    SessionLocal.configure(bind=engine)


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_missing_columns()
    _ensure_missing_indexes()


# create_all() only creates tables that don't exist yet - it never adds a
# column to a table that already exists, so a field added to an existing
# model (like Avatar.base_body_id) never appears on an already-provisioned
# production database on its own. Each entry is (table, column, DDL type) -
# the column is added with ALTER TABLE ADD COLUMN if missing. This runs
# before _ensure_missing_indexes() so any index on the new column has
# something to attach to.
_MISSING_COLUMN_TARGETS = [
    ("avatars", "base_body_id", "INTEGER NULL"),
]


def _ensure_missing_columns() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table_name, column_name, ddl_type in _MISSING_COLUMN_TARGETS:
        if table_name not in existing_tables:
            continue
        existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
        if column_name in existing_columns:
            continue
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl_type}"))
        except Exception:
            pass  # already added (race with another worker) or unsupported - non-fatal


# create_all() only creates tables that don't exist yet - it never alters an
# existing table, so a column changed from index=False to index=True (as
# happened for ItemTag.item_id / ItemAvatarRelation.item_id/avatar_id) never
# gets its index on an already-provisioned production database. Missing the
# item_tags.item_id index in particular meant every per-item tag lookup in a
# bulk operation (crawl, reclassify, library import) did a full table scan -
# on a ~35k-row table that made a reclassify run appear to hang indefinitely.
# This runs on every startup and is a no-op once the index exists.
_MISSING_INDEX_TARGETS = [
    ("item_tags", "ix_item_tags_item_id"),
    ("item_avatar_relations", "ix_item_avatar_relations_item_id"),
    ("item_avatar_relations", "ix_item_avatar_relations_avatar_id"),
    ("avatars", "ix_avatars_base_body_id"),
]


def _ensure_missing_indexes() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table_name, index_name in _MISSING_INDEX_TARGETS:
        if table_name not in existing_tables:
            continue
        table = Base.metadata.tables.get(table_name)
        if table is None:
            continue
        # index=True on the model column already attaches an Index object of
        # this exact name to the table's metadata - reuse it (checkfirst=True
        # makes this a no-op if the index already exists in the DB) instead
        # of constructing a second Index with the same name, which raises.
        index = next((idx for idx in table.indexes if idx.name == index_name), None)
        if index is None:
            continue
        try:
            index.create(bind=engine, checkfirst=True)
        except Exception:
            pass  # already exists (race with another worker) or unsupported - non-fatal


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
