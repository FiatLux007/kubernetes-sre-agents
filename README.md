# K8s-Agent

K8s-Agent is an AI-assisted Kubernetes incident diagnosis and remediation platform, powered by LangGraph, Celery, and real API integrations.

It runs the agent services, Redis, a k3s Kubernetes cluster, Robusta, and failing workloads through Docker Compose.

## Quick Start

```bash
cp .env.example .env
./demo up
```

The demo starts:

- `k8s-agent-api` in Docker Compose (FastAPI webhook receiver)
- `k8s-agent-worker` in Docker Compose (Celery + LangGraph remediation runtime)
- `k8s-agent-beat` in Docker Compose (Periodic Jira polling)
- `redis` in Docker Compose (State, caching, and deduplication)
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

## Features

**Supported:**
- OOMKilled diagnosis and automated PR generation
- CrashLoopBackOff diagnosis
- Real Jira integration (ticket creation, transitioning, and rich commenting)
- Real GitHub integration (branch creation, PR generation, file fetching)
- Real LLM integration (Anthropic API for diagnosis and YAML rewrites)
- LangGraph-powered Iterative Remediation (Human-in-the-loop via Jira and GitHub PR feedback)
- Redis deduplication by workload fingerprint with atomic correlation locks
- Celery Beat async polling for actionable tickets
- Robusta webhook integration
- k3s Kubernetes simulation inside Docker Compose
- Read-only Kubernetes context inspection (`kubectl get/describe/logs`)

**Not included (Future Roadmap):**
- Automatic production changes without human review
- PR merge automation
- Direct `kubectl apply` mutating operations by the agent
- Kafka / Qdrant for RAG-based historical incident retrieval
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

Copy `.env.example` to `.env` and fill real values to enable full functionality. The default has `DRY_RUN=true`, which mocks Jira issues, GitHub PRs, and LLM calls. Provide valid `LLM_API_KEY`, `JIRA_USER_EMAIL`, `JIRA_API_TOKEN`, and `GITHUB_TOKEN` to fully enable the remediation agent.

See [docs/configuration.md](docs/configuration.md) and [docs/progress.md](docs/progress.md) for architectural details.
