import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


class FakeRedis:
    def __init__(self):
        self.values = {}

    def ping(self):
        return True

    def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key, ttl):
        return True

    def hset(self, key, mapping):
        return True


def test_healthz():
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_with_fake_redis():
    with TestClient(app) as client:
        app.state.redis = FakeRedis()
        response = client.get("/readyz")
    assert response.status_code == 200


def test_webhook_accepts_oom(monkeypatch):
    settings = get_settings()
    settings.task_always_eager = True
    settings.dry_run = True

    payload = json.loads((Path(__file__).parent / "fixtures" / "oom_alert.json").read_text())
    with TestClient(app) as client:
        app.state.redis = FakeRedis()
        app.state.settings = settings
        response = client.post("/webhooks/robusta", json=payload)

    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] is True
    assert body["dedupe"]["is_new"] is True

