"""Чтение .env без внешних зависимостей."""

import os


def load_env(path: str = ".env"):
    """Загружает KEY=VALUE из .env в os.environ (не перекрывая заданные)."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip("'\"")
            os.environ.setdefault(key, value)
