"""GET-маршруты webapp: статика, SPA, конфиг, состояние, эмодзи."""

import core


def test_config(client):
    resp = client.get("/api/config")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_state_requires_auth(client):
    resp = client.get("/api/state")
    assert resp.status_code == 401
    assert resp.json() == {"ok": False, "error": "auth"}


def test_state_with_session(client, auth):
    token, _ = auth
    resp = client.get("/api/state", headers={"X-Session": token})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["name"] == "Тестовый"
    assert body["channels"] == [] and body["drafts"] == []


def test_emojis_grouped(client, auth, db):
    token, uid = auth
    db.epack_add(uid, "cats", "Котики", [("1" * 17, "😺")])
    resp = client.get("/api/emojis", headers={"X-Session": token})
    groups = resp.json()["groups"]
    assert len(groups) == 1 and groups[0]["name"] == "Котики"
    assert groups[0]["emojis"][0]["emoji_id"] == "1" * 17


def test_emoji_img_cached(client, monkeypatch):
    monkeypatch.setattr(core, "fetch_emoji_image", lambda eid: (b"PNG", "image/png"))
    resp = client.get("/api/emoji/img", params={"id": "123"})
    assert resp.status_code == 200
    assert resp.content == b"PNG"
    assert resp.headers["content-type"] == "image/png"


def test_emoji_img_rejects_bad_id(client):
    assert client.get("/api/emoji/img", params={"id": "abc"}).status_code == 404
    assert client.get("/api/emoji/img").status_code == 404


def test_spa_fallback_and_static(client):
    # /editor отдаёт SPA (index.html или editor.html)
    resp = client.get("/editor")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    # статика вне SPA
    assert client.get("/about").status_code == 200
    assert client.get("/favicon.svg").status_code == 200
    # неизвестный /api/ — 404 json, а не SPA
    resp = client.get("/api/nope")
    assert resp.status_code == 404
    assert resp.json()["ok"] is False


def test_assets_traversal_blocked(client):
    # сырые ../ httpx нормализует сам, поэтому шлём закодированные
    assert client.get("/assets/%2e%2e/%2e%2e/.env").status_code == 404
    assert client.get("/assets/nope.js").status_code == 404
