"""Тесты бэкенда: изолированная SQLite в tmp и клиент FastAPI-приложения."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import storage  # noqa: E402


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Чистая база на каждый тест."""
    monkeypatch.setattr(storage, "DB_FILE", str(tmp_path / "test.db"))
    monkeypatch.chdir(tmp_path)  # login_codes.json и прочие файлы — в tmp
    storage.init_db()
    return storage


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient

    import webapp
    return TestClient(webapp.app)


@pytest.fixture()
def auth(db):
    """Готовая сессия: (token, user_id)."""
    token = db.session_create(42, "Тестовый")
    return token, 42
