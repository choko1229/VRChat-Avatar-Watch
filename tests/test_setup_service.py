import pytest

from app.config import mysql_url
from app.services.setup_service import SetupError, SetupSettings, validate_setup_input


def valid_settings(**overrides):
    values = {
        "site_name": "VRChat Avatar Watch",
        "mysql_host": "127.0.0.1",
        "mysql_port": "3306",
        "mysql_database": "vrchat_avatar_watch",
        "mysql_user": "watch",
        "mysql_password": "pass:word",
        "discord_client_id": "client-id",
        "discord_client_secret": "client-secret",
        "discord_redirect_uri": "https://example.com/auth/discord/callback",
        "admin_discord_id": "",
        "crawl_interval_hours": "6",
        "min_crawl_interval_minutes": "30",
        "thumbnail_cache_max_gb": "10",
        "misskey_instance_url": "",
        "misskey_token": "",
        "discord_webhook_admin": "",
        "discord_webhook_public": "",
    }
    values.update(overrides)
    return SetupSettings(**values)


def test_validate_setup_requires_discord_auth():
    with pytest.raises(SetupError, match="Discord Client Secret"):
        validate_setup_input(valid_settings(discord_client_secret=""))


def test_validate_setup_requires_numeric_values():
    with pytest.raises(SetupError, match="数値"):
        validate_setup_input(valid_settings(crawl_interval_hours="six"))


def test_mysql_url_escapes_password():
    url = mysql_url("127.0.0.1", "3306", "db", "user", "p@ss:word")
    assert "p%40ss%3Aword" in url
