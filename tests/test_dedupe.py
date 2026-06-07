from app.dedupe import RedisDedupeStore
from app.robusta_parser import fingerprint, parse_robusta_payload


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.hashes = {}
        self.expirations = {}

    def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key, ttl):
        self.expirations[key] = ttl

    def hset(self, key, mapping):
        self.hashes[key] = mapping


def test_dedupe_first_then_duplicate():
    payload = {
        "reason": "OOMKilled",
        "labels": {
            "namespace": "demo",
            "workload": "api",
            "container": "app",
            "memory_limit": "1Gi",
        },
        "logs": "OOMKilled",
    }
    incident = parse_robusta_payload(payload)
    key = fingerprint(incident)
    store = RedisDedupeStore(FakeRedis(), ttl_seconds=300)

    first = store.record(key, incident)
    second = store.record(key, incident)

    assert first.is_new is True
    assert first.count == 1
    assert second.is_new is False
    assert second.count == 2

