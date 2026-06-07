# K8s-Agent V1 Demo

K8s-Agent V1 is a local demo for AI-assisted Kubernetes incident diagnosis.

It runs the agent services, Redis, a k3s Kubernetes cluster, Robusta, and failing workloads through Docker Compose.

## Quick Start

```bash
cp .env.example .env
./demo up
```

The demo starts:

- `k8s-agent-api` in Docker Compose
- `k8s-agent-worker` in Docker Compose
- `redis` in Docker Compose
- `k3s` in Docker Compose
- Robusta inside k3s
- `oom-demo` and `crashloop-demo` inside k3s

No local FastAPI, Celery, Redis, minikube, kubectl, or Helm installation is required.

## Demo Commands

```bash
./demo status
./demo trigger oom
./demo trigger crashloop
./demo logs
```

The API is exposed on:

```text
http://localhost:18080
```

Robusta calls the webhook from inside the Docker Compose network through:

```text
http://k8s-agent-api:8000/webhooks/robusta
```

## V1 Scope

Supported:

- OOMKilled diagnosis and dry-run PR recommendation
- CrashLoopBackOff diagnosis only
- Redis dedupe by workload fingerprint
- dry-run Jira/GitHub/LLM adapters
- Robusta webhook integration
- k3s Kubernetes simulation inside Docker Compose

Not included in V1:

- automatic production changes
- PR merge automation
- direct `kubectl apply` by the agent
- Kafka
- Qdrant
- LangGraph
- Istio or Argo Rollouts

## Development

```bash
uv run --extra test pytest
./demo up
./demo status
curl -X POST http://localhost:18080/webhooks/robusta \
  -H "Content-Type: application/json" \
  --data @tests/fixtures/oom_alert.json
./demo logs
```

## Configuration

Copy `.env.example` to `.env` and fill real values when needed. The default is `DRY_RUN=true`, so no real Jira issue, GitHub PR, or LLM call is made.

See [docs/configuration.md](docs/configuration.md).
