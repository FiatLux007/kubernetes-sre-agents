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

## Current Architecture State

- **Event Source**: Robusta (Running in K3s)
- **Queue/State**: Redis (Handles event deduplication and Jira ticket correlation locks)
- **Message Bus**: Jira Kanban Board (Stores agent JSON context and human feedback)
- **Workers**: Celery Workers & Celery Beat (Executes the Discovery Agent and the Polling Remediation Agent)
- **Deployment Strategy**: ArgoCD GitOps Pull model via GitHub.

## Next Steps (Roadmap)

1. **LangGraph Migration**: Restructure the linear logic into a stateful LangGraph to support multi-step reasoning, self-reflection, and broader tool use (e.g. executing `kubectl` commands based on PR comments).
2. **Kafka/Qdrant**: (Future Scalability) Introduce Kafka for high-throughput event processing and Qdrant for RAG-based historical incident retrieval.
