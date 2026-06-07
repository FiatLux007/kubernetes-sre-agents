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

## Useful Checks

```bash
./demo status
curl http://localhost:18080/healthz
curl http://localhost:18080/readyz
```

## Cleanup Notes

This project intentionally does not provide a bulk delete script.

Use explicit commands when you want to clean up:

```bash
docker compose down
```
