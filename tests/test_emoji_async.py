"""Асинхронная загрузка эмодзи: прогрев, single-flight, negative-cache."""

import asyncio

import pytest

import core


@pytest.fixture(autouse=True)
def clean_caches(monkeypatch):
    monkeypatch.setattr(core, "EMOJI_CACHE", {})
    monkeypatch.setattr(core, "EMOJI_FAILED", {})
    monkeypatch.setattr(core, "_emoji_tasks", {})


def _fake_tg(calls, stickers_by_id):
    """Мок _tg_api: считает вызовы, отдаёт метаданные и пути файлов."""
    async def fake(method, payload):
        calls.append((method, payload))
        if method == "getCustomEmojiStickers":
            return [stickers_by_id[e] for e in payload["custom_emoji_ids"]
                    if e in stickers_by_id]
        if method == "getFile":
            return {"file_path": f"stickers/{payload['file_id']}.webp"}
        return None
    return fake


def test_prefetch_batches_and_caches(monkeypatch):
    ids = [str(i) * 5 for i in range(1, 4)]
    stickers = {e: {"custom_emoji_id": e, "file_id": "f" + e} for e in ids}
    calls = []
    monkeypatch.setattr(core, "_tg_api", _fake_tg(calls, stickers))
    async def fake_dl(path):
        return b"IMG" + path.encode()
    monkeypatch.setattr(core, "_tg_download", fake_dl)

    asyncio.run(core.prefetch_emojis(ids))

    # метаданные всего списка — одним вызовом, не тремя
    meta_calls = [c for c in calls if c[0] == "getCustomEmojiStickers"]
    assert len(meta_calls) == 1
    assert meta_calls[0][1]["custom_emoji_ids"] == ids
    assert set(core.EMOJI_CACHE) == set(ids)
    assert core.EMOJI_CACHE[ids[0]][1] == "image/webp"


def test_prefetch_skips_cached(monkeypatch):
    core.EMOJI_CACHE["11111"] = (b"x", "image/webp")
    calls = []
    monkeypatch.setattr(core, "_tg_api", _fake_tg(calls, {}))
    asyncio.run(core.prefetch_emojis(["11111"]))
    assert calls == []  # всё в кэше — в Telegram не ходим


def test_single_flight(monkeypatch):
    """Десять одновременных запросов одного id — одно скачивание."""
    started = []

    async def slow_load(eid, st):
        started.append(eid)
        await asyncio.sleep(0.01)
        core.EMOJI_CACHE[eid] = (b"IMG", "image/webp")
        return core.EMOJI_CACHE[eid]
    monkeypatch.setattr(core, "_load_emoji", slow_load)

    async def hammer():
        return await asyncio.gather(*(core.emoji_image("77777") for _ in range(10)))
    results = asyncio.run(hammer())
    assert started == ["77777"]
    assert all(r == (b"IMG", "image/webp") for r in results)


def test_failure_remembered_then_retried(monkeypatch):
    async def fail_api(method, payload):
        return None
    monkeypatch.setattr(core, "_tg_api", fail_api)

    assert asyncio.run(core.emoji_image("99999")) is None
    assert "99999" in core.EMOJI_FAILED
    # повторный запрос в течение минуты не ходит в Telegram
    calls = []
    monkeypatch.setattr(core, "_tg_api", _fake_tg(calls, {}))
    assert asyncio.run(core.emoji_image("99999")) is None
    assert calls == []
    # после TTL — новая попытка
    core.EMOJI_FAILED["99999"] = 0
    stickers = {"99999": {"custom_emoji_id": "99999", "file_id": "f9"}}
    monkeypatch.setattr(core, "_tg_api", _fake_tg(calls, stickers))
    async def fake_dl(path):
        return b"OK"
    monkeypatch.setattr(core, "_tg_download", fake_dl)
    assert asyncio.run(core.emoji_image("99999")) == (b"OK", "image/webp")
