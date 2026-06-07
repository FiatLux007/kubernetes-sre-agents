# Demo Quickstart

## Prerequisites

Install:

- Docker with Docker Compose

No local minikube, kubectl, Helm, Python, FastAPI, Celery, or Redis installation is required.

## Start

```bash
cp .env.example .env
./demo up
```

`./demo up` performs:

1. checks required tools
2. builds the K8s-Agent and bootstrap images from a clean Docker-only context
3. starts Redis, API, Worker, and k3s with Docker Compose
4. waits for `/healthz` and `/readyz`
5. runs the bootstrap container
6. installs or upgrades Robusta inside k3s
7. applies demo workloads inside k3s

## Trigger Incidents

```bash
./demo trigger oom
./demo trigger crashloop
./demo logs
```

The OOM demo should produce a diagnosis and PR recommendation in dry-run logs.

The CrashLoopBackOff demo should produce a diagnosis only.

## Reset Demo Dedupe State

Redis stores short-lived dedupe keys and active Jira correlations. Clear them before repeating the same incident test when you want the agent to process it as a fresh event, especially after switching between dry-run and real Jira/PR testing.

```bash
docker compose -f docker-compose.yml exec -T redis redis-cli --scan \
  | grep -E '^(active_issue:k8s-agent-demo:|incident:k3s-k8s-agent-demo:k8s-agent-demo:)' \
  | xargs -r docker compose -f docker-compose.yml exec -T redis redis-cli DEL
```

## Useful Checks

```bash
./demo status
curl http://localhost:18080/healthz
curl http://localhost:18080/readyz
```

## Cleanup Notes

Stop and remove the demo containers and network:

```bash
./demo down
```

`./demo down` keeps Docker volumes and local images. If you want to delete k3s and Redis state as well, run:

```bash
docker compose down -v
```
