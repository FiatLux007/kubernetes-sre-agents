# K8s Agent Progress Summary

*Last Updated: 2026-06-07*

## Achievements & Completed Milestones

### 1. True Async Iterative Remediation Agent (Human-in-the-loop)
- **Decoupled "Jira-as-a-Bus" Architecture**: Transformed the synchronous pipeline into an asynchronous, poll-based architecture. The initial Discovery Agent now simply creates a Jira ticket with an `AI-Remediation` label and embeds a hidden machine-readable JSON context, then immediately exits.
- **Celery Beat Polling**: Implemented a standalone `k8s-agent-beat` service that securely polls the Jira API (`/rest/api/2/search/jql`) every 60 seconds for actionable tickets, bypassing firewall and webhook limitations for local dev.
- **Iterative LLM Code Writing**: The Remediation Agent fetches human feedback from Jira comments and review notes from GitHub PRs. It uses Claude to iteratively rewrite the GitOps YAML manifests, allowing engineers to refine code changes by simply dragging the Jira ticket back to "To Do" and leaving a comment.

### 2. GitHub HTTP Client Integration
- **Auto-PR Generation**: Implemented a robust GitHub adapter. When the Agent rewrites a configuration (e.g., bumping memory limits), it automatically creates or updates a branch (`ai-fix/kan-xx`), pushes the YAML file via API, and opens a Pull Request on `zyusong0614/k8s-agent-gitops`.

### 3. Real API Integrations (Replacing Dry-Runs)
- **Jira HTTP Client**: The agent creates actual Jira tickets and adds rich comments using standard REST APIs.
- **LLM HTTP Client**: Integrated the Anthropic HTTP API to perform real-time, context-aware diagnosis on Kubernetes alerts based on Robusta logs.
- **Ticket Correlation & De-duplication**: 
  - Implemented a stateful Redis store (`active_issue:{namespace}:{workload_name}`) with a 1-hour correlation window. 
  - Subsequent incidents (e.g., repeating CrashLoopBackOff loops) are now correctly appended as comments under the existing Jira ticket rather than creating new, duplicate tickets.

### 4. Infrastructure & GitOps Automation
- **ArgoCD Integration**: Evolved the local Docker Compose bootstrap process (`bootstrap.sh`) to automatically install ArgoCD within the `k3s` cluster.
- **Automated Synchronization**: Configured an ArgoCD `Application` resource with `Automated Sync`. The cluster state is now completely declarative and bound to the GitHub repository.
- **Repository Security & Open Source Readiness**: 
  - Purged all hardcoded personal configurations, secrets, and API tokens (Anthropic, Jira, GitHub) from `docker-compose.yml`.
  - Enforced a strict separation of configuration via a local `.env` file using the 12-Factor App methodology.

### 5. LangGraph Remediation Workflow Migration
- **Stateful RemediationGraph**: Migrated the linear Jira polling remediation logic into a LangGraph state machine running inside the existing Celery worker process. LangGraph is not a separate service and does not replace Docker Compose, Celery, Redis, Jira, GitHub, or ArgoCD.
- **Graph Checkpointing**: Added SQLite-based LangGraph checkpointing with a Docker volume, using `thread_id = remediation:{issue_key}` for stable per-ticket state.
- **Structured Agent Flow**: Split remediation into deterministic graph nodes: claim Jira issue, load Jira context, parse hidden JSON context, load GitHub PR comments, fetch GitOps manifest, plan remediation, optionally collect Kubernetes context, rewrite YAML, validate manifest, self-reflect on validation errors, publish PR, and finalize Jira.
- **Read-only Kubernetes Tooling**: Added a bounded `kubectl` context tool for read-only inspection (`get`, `describe`, `logs`). Mutating operations such as `apply`, `patch`, `delete`, `scale`, `exec`, and `rollout restart` remain forbidden.
- **Validation and Retry Loop**: Added deterministic YAML/Kubernetes manifest validation plus a bounded self-reflection loop before publishing any PR. Field-level mutation allowlists are intentionally not enforced yet, so human PR review remains the final safety gate.
- **Worker Integration**: Kept Celery Beat's Jira polling loop intact, but replaced the old inline remediation body with a call to `run_remediation(...)`. Polling results now track both processed and failed graph runs.
- **Test Coverage**: Added unit, graph, and worker tests covering context parsing, routing, validation, forbidden kubectl operations, happy-path PR publication, missing context, missing manifests, validation repair, retry exhaustion, Kubernetes context loading, and worker polling behavior.

### 6. Duplicate Ticket and Correlation Hardening
- **Workload-level Fingerprints**: Tightened Redis dedupe keys so pod-specific Robusta titles and pod template hashes no longer create separate incident fingerprints for the same workload/error class.
- **Atomic Jira Correlation Lock**: Added a Redis `SET nx ex` lock around Jira issue creation for `active_issue:{namespace}:{workload_name}`. Concurrent Celery workers now wait for the correlated issue key and append comments instead of racing to create duplicate tickets.
- **Regression Tests**: Added tests proving that pod hash changes do not change the incident fingerprint, and that a worker encountering an in-flight correlation lock appends to the existing issue instead of creating a new Jira ticket.
- **Manual Dry-run Validation**: Verified the Docker Compose dry-run path: Robusta -> FastAPI webhook -> Redis dedupe -> Celery worker -> dry-run LLM/Jira handling. Also verified RemediationGraph execution inside the worker container with fake Jira/GitHub/LLM clients.

### 7. Reliability and Ticket Lifecycle Improvements
- **Infinite Remediation Loop Prevention**: Differentiated permanent from temporary errors in LangGraph. Permanent validation or missing-file errors now shift the ticket to `In Review`, removing it from the polling queue. Temporary API errors keep the ticket in `To Do` for automatic retries.
- **Dynamic AI-Remediation Labeling**: Corrected Jira label assignment. Only actionable incidents where `pr_required` is true get the `AI-Remediation` label. Diagnostics and unsupported alerts get `AI-Generated` instead, preventing them from being erroneously picked up by the remediation polling loop.
- **JQL Deduplication Fallback**: Implemented a secondary Jira Search (JQL) fallback for ticket deduplication. If the Redis cache fails or expires, the system queries Jira directly for active tickets with matching namespaces and workloads, reliably appending context instead of creating duplicate tickets.

## Current Architecture State

- **Event Source**: Robusta (Running in K3s)
- **Queue/State**: Redis (Handles event deduplication, active issue correlation, and correlation creation locks)
- **Message Bus**: Jira Kanban Board (Stores agent JSON context and human feedback)
- **Workers**: Celery Workers & Celery Beat (Executes the Discovery Agent and invokes LangGraph RemediationGraph from the worker)
- **Agent Runtime**: LangGraph runs in-process inside `k8s-agent-worker`; it is a workflow/state-machine layer, not a standalone container.
- **Deployment Strategy**: ArgoCD GitOps Pull model via GitHub.

## Next Steps (Roadmap)

1. **Production Hardening for LangGraph**: Add richer graph observability, optional Postgres checkpointing, and clearer operator-facing trace summaries in Jira comments.
2. **Remediation Policy Expansion**: Decide when to introduce field-level mutation allowlists or incident-type-specific subgraphs for OOM, CrashLoopBackOff, ImagePullBackOff, and rollout failures.
3. **Kafka/Qdrant**: (Future Scalability) Introduce Kafka for high-throughput event processing and Qdrant for RAG-based historical incident retrieval.
