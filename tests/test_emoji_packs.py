"""Импорт эмодзи-паков по ссылке и каталог."""

import core


def test_parse_pack_link():
    assert core.parse_pack_link("https://t.me/addemoji/Cool_Pack1") == "Cool_Pack1"
    assert core.parse_pack_link("t.me/addemoji/Pack/") == "Pack"
    assert core.parse_pack_link("telegram.me/addstickers/Pack") == "Pack"
    assert core.parse_pack_link("BarePackName") == "BarePackName"
    assert core.parse_pack_link("не ссылка вовсе") is None
    assert core.parse_pack_link("https://evil.com/addemoji/Pack") is None


def _fake_set(name="CatsPack", stype="custom_emoji", n=3):
    return (True, {"name": name, "title": "Котики", "sticker_type": stype,
                   "stickers": [{"custom_emoji_id": str(i) * 17, "emoji": "😺"}
                                for i in range(1, n + 1)]})


def test_import_pack(db, monkeypatch):
    monkeypatch.setattr(core, "api_call", lambda m, **kw: _fake_set())
    ok, title = core.import_emoji_pack(42, "CatsPack")
    assert ok and title == "Котики"
    packs = db.epacks_list(42)
    assert len(packs) == 1 and packs[0]["count"] == 3


def test_import_rejects_sticker_set(db, monkeypatch):
    monkeypatch.setattr(core, "api_call", lambda m, **kw: _fake_set(stype="regular"))
    ok, err = core.import_emoji_pack(42, "JustStickers")
    assert not ok and "не кастомные эмодзи" in err


def test_catalog_endpoint(client, auth, db, monkeypatch):
    token, uid = auth
    # чужой популярный пак + свой установленный
    db.epack_add(7, "PopularPack", "Популярный", [("9" * 17, "🔥")])
    db.epack_add(uid, "MinePack", "Мой", [("8" * 17, "🌟")])
    resp = client.get("/api/emoji/catalog", headers={"X-Session": token})
    packs = {p["set_name"]: p for p in resp.json()["packs"]}
    assert packs["PopularPack"]["installed"] is False
    assert packs["MinePack"]["installed"] is True


def test_pack_add_endpoint(client, auth, monkeypatch):
    token, _ = auth
    monkeypatch.setattr(core, "api_call", lambda m, **kw: _fake_set())
    resp = client.post("/api/emoji/packs/add",
                       json={"link": "https://t.me/addemoji/CatsPack"},
                       headers={"X-Session": token})
    assert resp.json() == {"ok": True, "title": "Котики"}
    resp = client.post("/api/emoji/packs/add", json={"link": "???"},
                       headers={"X-Session": token})
    assert resp.json()["ok"] is False
