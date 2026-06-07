from __future__ import annotations

from app.schemas import DedupeResult, IncidentPayload


class RedisDedupeStore:
    def __init__(self, redis, ttl_seconds: int):
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    def record(self, key: str, incident: IncidentPayload) -> DedupeResult:
        count = int(self.redis.incr(key))
        if count == 1:
            self.redis.expire(key, self.ttl_seconds)
        self.redis.hset(f"{key}:meta", mapping={
            "namespace": incident.namespace,
            "workload_name": incident.workload_name,
            "reason": incident.reason,
            "last_pod_name": incident.pod_name,
        })
        self.redis.expire(f"{key}:meta", self.ttl_seconds)
        return DedupeResult(key=key, is_new=count == 1, count=count)
