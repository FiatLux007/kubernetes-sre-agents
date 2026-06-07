# Security Boundaries

K8s-Agent V1 is an assistant, not an autonomous production mutator.

## Allowed

- receive Robusta webhook payloads
- summarize logs and Kubernetes context
- classify OOMKilled and CrashLoopBackOff
- write dry-run Jira output
- write dry-run GitHub PR output
- recommend a memory limit change for OOMKilled if policy allows

## Forbidden

- direct `kubectl apply`
- direct `kubectl delete`
- direct production cluster mutation
- PR merge automation
- ArgoCD sync automation
- Secret modification
- RBAC modification
- Service selector modification
- NetworkPolicy relaxation
- deleting readiness or liveness probes
- deleting resource requests or limits

## Policy Defaults

OOM memory recommendations:

- must know the current memory limit
- may propose at most 2x current limit
- must not exceed `MAX_MEMORY_LIMIT_GI`
- must go through human review

