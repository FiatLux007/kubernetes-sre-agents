# Architecture V1

V1 is intentionally small: it proves the alert-to-diagnosis-to-PR-recommendation loop without allowing the agent to mutate production.

```text
k3s in docker-compose:
  failing workload
  -> Robusta
  -> webhook to http://k8s-agent-api:8000

docker-compose:
  k3s
  bootstrap
  k8s-agent-api
  -> Redis dedupe
  -> Celery worker
  -> Agent diagnosis
  -> dry-run Jira/GitHub/LLM adapters
```

## Components

- FastAPI receives Robusta webhook payloads at `/webhooks/robusta`.
- Redis stores dedupe counters keyed by stable workload fingerprint.
- Celery processes incidents asynchronously.
- k3s provides the local Kubernetes API from inside Docker Compose.
- The bootstrap container contains kubectl and Helm, installs Robusta, and applies demo workloads.
- The V1 agent classifies OOMKilled and CrashLoopBackOff.
- Jira, GitHub, and LLM clients are adapters. They default to dry-run.

## Data Flow

```text
Robusta payload
-> parse and normalize
-> fingerprint
-> Redis dedupe
-> Celery task
-> diagnose
-> policy check
-> dry-run Jira issue/comment
-> optional dry-run GitHub PR
```

## Extension Points

- Replace dry-run clients with Jira/GitHub/LLM HTTP clients or MCP adapters.
- Replace single-agent flow with LangGraph.
- Replace Redis/Celery with Kafka if event volume requires it.
- Add Qdrant once closed incidents exist.
- Add staging verification after PR generation is trusted.
