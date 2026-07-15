from fastapi.testclient import TestClient

from app.main import create_app


def _client_with_setup_complete(monkeypatch):
    import app.main as main_module

    class Config:
        site_name = "VRChat Avatar Watch"
        session_secret = "test-secret"
        setup_complete = True

    monkeypatch.setattr(main_module, "get_config", lambda: Config())
    return TestClient(create_app(), follow_redirects=False)


def test_avatars_reclassify_route_is_not_shadowed_by_avatar_id_route(monkeypatch):
    # /avatars/{avatar_id} was registered before /avatars/reclassify, so a
    # POST to /admin/avatars/reclassify used to be matched by the
    # {avatar_id}: int route first, failing with a 422 "unable to parse
    # 'reclassify' as an integer" instead of ever reaching the reclassify
    # handler. Without a session this should get as far as the admin-auth
    # check (401), never a path-parameter validation error (422).
    client = _client_with_setup_complete(monkeypatch)
    response = client.post("/admin/avatars/reclassify", data={"csrf": "x"})
    assert response.status_code == 401


def test_avatar_id_routes_still_resolve_with_numeric_ids(monkeypatch):
    client = _client_with_setup_complete(monkeypatch)
    for path in ["/admin/avatars/123", "/admin/avatars/123/refresh", "/admin/avatars/123/delete"]:
        response = client.post(path, data={"csrf": "x"})
        assert response.status_code == 401, path
