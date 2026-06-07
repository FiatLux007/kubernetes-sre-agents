# k3s in Docker Compose V1

The demo does not require local minikube, kubectl, or Helm.

Docker Compose starts:

- `k3s`: a single-node Kubernetes cluster
- `bootstrap`: a helper container with kubectl and Helm
- `k8s-agent-api`
- `k8s-agent-worker`
- `redis`

## Bootstrap Flow

```text
k3s writes kubeconfig to a Docker volume
-> bootstrap waits for kubeconfig
-> bootstrap waits for k3s node readiness
-> bootstrap waits for K8s-Agent /readyz
-> bootstrap installs Robusta
-> bootstrap applies demo workloads
```

Robusta sends webhooks to:

```text
http://k8s-agent-api:8000/webhooks/robusta
```

That address works because Robusta runs inside the k3s environment started by Docker Compose, and the agent API is on the same Compose network.

