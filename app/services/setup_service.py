from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AdminUser, Setting
from app.services.seed import seed_defaults


@dataclass(frozen=True)
class SetupSettings:
    site_name: str
    mysql_host: str
    mysql_port: str
    mysql_database: str
    mysql_user: str
    mysql_password: str
    discord_client_id: str
    discord_client_secret: str
    discord_redirect_uri: str
    admin_discord_id: str
    crawl_interval_hours: str
    min_crawl_interval_minutes: str
    thumbnail_cache_max_gb: str
    misskey_instance_url: str
    misskey_token: str
    discord_webhook_admin: str
    discord_webhook_public: str


class SetupError(Exception):
    pass


def validate_setup_input(settings: SetupSettings) -> None:
    required = {
        "MySQL host": settings.mysql_host,
        "MySQL port": settings.mysql_port,
        "MySQL database": settings.mysql_database,
        "MySQL user": settings.mysql_user,
        "Discord Client ID": settings.discord_client_id,
        "Discord Client Secret": settings.discord_client_secret,
        "Discord Redirect URI": settings.discord_redirect_uri,
    }
    missing = [label for label, value in required.items() if not value.strip()]
    if missing:
        raise SetupError(f"必須項目が未入力です: {', '.join(missing)}")
    for label, value in {
        "MySQL port": settings.mysql_port,
        "クロール間隔": settings.crawl_interval_hours,
        "最小再取得間隔": settings.min_crawl_interval_minutes,
        "サムネイル最大容量": settings.thumbnail_cache_max_gb,
    }.items():
        try:
            parsed = int(value)
        except ValueError as exc:
            raise SetupError(f"{label} は数値で入力してください") from exc
        if parsed < 0:
            raise SetupError(f"{label} は0以上で入力してください")


def create_tables_and_seed(database_url: str, settings: SetupSettings) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
        db = SessionLocal()
        try:
            seed_defaults(db)
            persist_settings(db, settings)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except SQLAlchemyError as exc:
        raise SetupError("MySQL接続またはテーブル作成に失敗しました。接続情報とDB権限を確認してください。") from exc
    finally:
        engine.dispose()


def persist_settings(db, settings: SetupSettings) -> None:
    payload = {
        "site_name": (settings.site_name, False),
        "mysql_host": (settings.mysql_host, False),
        "mysql_port": (settings.mysql_port, False),
        "mysql_database": (settings.mysql_database, False),
        "mysql_user": (settings.mysql_user, False),
        "mysql_password": (settings.mysql_password, True),
        "discord_client_id": (settings.discord_client_id, False),
        "discord_client_secret": (settings.discord_client_secret, True),
        "discord_redirect_uri": (settings.discord_redirect_uri, False),
        "admin_discord_id": (settings.admin_discord_id, False),
        "crawl_interval_hours": (settings.crawl_interval_hours, False),
        "min_crawl_interval_minutes": (settings.min_crawl_interval_minutes, False),
        "thumbnail_cache_max_gb": (settings.thumbnail_cache_max_gb, False),
        "misskey_instance_url": (settings.misskey_instance_url, False),
        "misskey_token": (settings.misskey_token, True),
        "discord_webhook_admin": (settings.discord_webhook_admin, True),
        "discord_webhook_public": (settings.discord_webhook_public, True),
    }
    for key, (value, is_secret) in payload.items():
        setting = db.scalar(select(Setting).where(Setting.key == key))
        if not setting:
            setting = Setting(key=key, is_secret=is_secret)
            db.add(setting)
        setting.value = value
        setting.is_secret = is_secret
    if settings.admin_discord_id and not db.scalar(select(AdminUser).where(AdminUser.discord_id == settings.admin_discord_id)):
        db.add(AdminUser(discord_id=settings.admin_discord_id))
