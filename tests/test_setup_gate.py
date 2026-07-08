from fastapi.testclient import TestClient

from app.main import create_app, should_redirect_to_setup


def test_setup_gate_rules():
    assert should_redirect_to_setup("/", setup_complete=False) is True
    assert should_redirect_to_setup("/admin", setup_complete=False) is True
    assert should_redirect_to_setup("/setup", setup_complete=False) is False
    assert should_redirect_to_setup("/api/health", setup_complete=False) is False
    assert should_redirect_to_setup("/static/css/app.css", setup_complete=False) is False
    assert should_redirect_to_setup("/", setup_complete=True) is False


def test_setup_is_shown_automatically_when_incomplete(monkeypatch):
    import app.main as main_module

    class Config:
        site_name = "VRChat Avatar Watch"
        session_secret = "test-secret"
        setup_complete = False

    monkeypatch.setattr(main_module, "get_config", lambda: Config())
    client = TestClient(create_app())
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/setup"
    assert client.get("/setup").status_code == 200
    assert client.get("/api/health").status_code == 200


def test_setup_is_not_accessible_after_completion(monkeypatch):
    import app.routers.setup as setup_router

    class Config:
        site_name = "VRChat Avatar Watch"
        session_secret = "test-secret"
        setup_complete = True

    monkeypatch.setattr(setup_router, "get_config", lambda: Config())
    client = TestClient(create_app())
    response = client.get("/setup", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"

    post_response = client.post(
        "/setup",
        data={
            "csrf": "bad",
            "mysql_host": "127.0.0.1",
            "mysql_database": "db",
            "mysql_user": "user",
            "discord_client_id": "client",
            "discord_client_secret": "secret",
            "discord_redirect_uri": "https://example.com/auth/discord/callback",
        },
    )
    assert post_response.status_code == 403


def test_setup_post_shows_error_without_marking_complete(monkeypatch):
    import app.routers.setup as setup_router

    def fail_setup(*args, **kwargs):
        raise setup_router.SetupError("MySQL接続またはテーブル作成に失敗しました。")

    monkeypatch.setattr(setup_router, "create_tables_and_seed", fail_setup)
    client = TestClient(create_app())
    response = client.post(
        "/setup",
        data={
            "csrf": client.get("/setup").text.split('name="csrf" value="', 1)[1].split('"', 1)[0],
            "site_name": "VRChat Avatar Watch",
            "mysql_host": "127.0.0.1",
            "mysql_port": "3306",
            "mysql_database": "db",
            "mysql_user": "user",
            "mysql_password": "secret",
            "discord_client_id": "client",
            "discord_client_secret": "secret",
            "discord_redirect_uri": "https://example.com/auth/discord/callback",
            "crawl_interval_hours": "6",
            "min_crawl_interval_minutes": "30",
            "thumbnail_cache_max_gb": "10",
        },
    )
    assert response.status_code == 400
    assert "MySQL接続またはテーブル作成に失敗しました" in response.text
