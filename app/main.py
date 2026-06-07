from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from app.agent import handle_incident
from app.config import get_settings
from app.dedupe import RedisDedupeStore
from app.robusta_parser import fingerprint, parse_robusta_payload
from app.worker import process_incident

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from redis import Redis

    settings = get_settings()
    app.state.settings = settings
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    yield


app = FastAPI(title="K8s-Agent V1", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict:
    try:
        app.state.redis.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"redis unavailable: {exc}") from exc
    return {"status": "ready"}


@app.post("/webhooks/robusta", status_code=202)
async def robusta_webhook(request: Request) -> dict:
    try:
        payload = await request.json()
        logger.info("Received JSON payload: %s", payload)
    except Exception as e:
        body = await request.body()
        logger.error("Failed to parse JSON. Raw body: %s", body)
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    settings = app.state.settings
    incident = parse_robusta_payload(payload)
    key = fingerprint(incident)
    dedupe = RedisDedupeStore(app.state.redis, settings.dedupe_ttl_seconds)
    result = dedupe.record(key, incident)

    if result.is_new:
        if settings.task_always_eager:
            handle_incident(payload, settings, app.state.redis)
        else:
            process_incident.delay(payload)
        logger.info("webhook.accepted key=%s workload=%s/%s", key, incident.namespace, incident.workload_name)
    else:
        logger.info("webhook.duplicate key=%s count=%s", key, result.count)

    return {"accepted": True, "dedupe": result.model_dump()}
