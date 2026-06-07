# Deprecated: Minikube + Robusta V1

The V1 demo now uses k3s inside Docker Compose instead of minikube.

Use:

```bash
./demo up
```

The current Kubernetes-in-Compose documentation is [k3s-compose-v1.md](k3s-compose-v1.md).

## Robusta Configuration

The template is:

```text
deploy/robusta/values.template.yaml
```

The rendered values define:

- `sinksConfig` with a `webhook_sink`
- `customPlaybooks` for Kubernetes warning events including `OOMKilled`, `BackOff`, and `CrashLoopBackOff`

## Demo Workloads

```text
deploy/workloads/oom-demo.yaml
deploy/workloads/crashloop-demo.yaml
```

The OOM workload allocates memory until it exceeds a small memory limit.

The CrashLoop workload exits immediately with a clear startup error.
