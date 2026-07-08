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
