# LangGraph Migration Design

*Last Updated: 2026-06-07*

## Purpose

This document defines the first LangGraph migration step for K8s-Agent. The goal is to convert the current linear Jira polling remediation flow into a stateful, recoverable graph while preserving the existing external architecture:

- FastAPI and Robusta remain the alert ingestion path.
- Redis remains responsible for alert dedupe and active issue correlation.
- Celery Beat remains responsible for polling Jira.
- Jira remains the human-in-the-loop message bus.
- GitHub PRs remain the only write path for Kubernetes manifest changes.
- ArgoCD remains responsible for applying GitOps changes to the cluster.

The first migration should not turn the project into an unrestricted autonomous SRE agent. It should make the existing remediation workflow more observable, resumable, testable, and easier to extend.

## Scope

### In Scope

- Migrate `poll_jira_for_remediation` into a LangGraph-backed remediation workflow.
- Keep `handle_incident` and Discovery Agent behavior unchanged.
- Add graph checkpointing using a local SQLite checkpointer for the demo environment.
- Use Jira issue key as the stable graph thread identity.
- Add structured remediation planning before YAML rewrite.
- Add deterministic YAML and Kubernetes manifest validation.
- Add bounded self-reflection and retry after validation failures.
- Add read-only `kubectl` context collection as a graph tool.
- Keep PR publication through the existing GitHub HTTP client.
- On graph failure, add a Jira comment and transition the issue back to `To Do`.

### Out of Scope

- Replacing Celery with LangGraph runtime infrastructure.
- Replacing Jira with LangGraph interrupts.
- Introducing Kafka or Qdrant.
- Allowing direct Kubernetes mutations from the agent.
- Applying changes to the cluster with `kubectl apply`, `patch`, `delete`, or `scale`.
- Migrating all incident discovery logic into LangGraph.

## Current Remediation Flow

The current remediation logic lives in `app.worker.poll_jira_for_remediation`:

```text
Celery Beat
-> search Jira for To Do + AI-Remediation issues
-> transition issue to In Progress
-> fetch Jira description/comments
-> parse workload_name from hidden JSON block
-> fetch GitHub PR comments
-> fetch GitOps YAML from GitHub
-> ask LLM to rewrite YAML
-> push file to ai-fix/{issue_key}
-> create or update PR
-> comment on Jira
-> transition issue to In Review
```

This is functionally correct for the demo, but it has weak internal recovery boundaries. If any step fails, the worker has limited visibility into which intermediate artifacts were produced and whether a retry should reuse them.

## Target Architecture

```text
Robusta
-> FastAPI webhook
-> Redis dedupe/correlation
-> Discovery Agent
-> Jira issue with AI-Remediation label

Celery Beat
-> poll Jira To Do + AI-Remediation
-> invoke LangGraph RemediationGraph
-> GitHub branch and PR
-> Jira In Review
-> ArgoCD syncs after human-approved GitOps merge
```

LangGraph becomes the internal remediation state machine. It does not become the event queue, the human collaboration channel, or the production deployment mechanism.

## Thread Identity and Checkpointing

Each Jira issue gets one graph thread:

```text
thread_id = remediation:{issue_key}
```

Example:

```python
config = {"configurable": {"thread_id": f"remediation:{issue_key}"}}
graph.invoke({"issue_key": issue_key, "issue_url": issue.url}, config=config)
```

For the local demo, use SQLite checkpointing with a Docker volume. This keeps graph state across worker restarts without introducing a new database. Production can later move to Postgres checkpointing without changing graph semantics.

## Graph State

The state should be explicit and serializable. It should store the minimum data needed to resume, inspect, and explain a remediation run.

```python
from typing import Any, TypedDict


class RemediationState(TypedDict, total=False):
    issue_key: str
    issue_url: str
    jira_status: str

    description: str
    jira_comments: list[str]
    pr_comments: list[str]
    human_feedback: list[str]

    workload_name: str
    namespace: str
    branch: str
    file_path: str

    original_yaml: str
    proposed_yaml: str
    remediation_plan: dict[str, Any]
    k8s_context: dict[str, Any]

    validation_passed: bool
    validation_errors: list[str]
    retry_count: int
    max_retries: int

    pr_title: str
    pr_url: str
    failure_reason: str
    next_action: str
```

Avoid storing secrets. If future Kubernetes context includes large logs or describe snapshots, store short excerpts in state and keep full artifacts elsewhere.

## Graph Nodes

### `claim_issue`

Purpose:

- Mark the Jira issue as actively handled.
- Initialize stable branch and retry metadata.

Actions:

- Create `JiraIssue`.
- Transition issue to `In Progress`.
- Set `branch = ai-fix/{issue_key.lower()}`.
- Set `retry_count = 0` if not present.
- Set `max_retries = 2` if not present.

Idempotency:

- Re-transitioning an issue to `In Progress` should be tolerated.
- If the issue is already in progress, continue.

### `load_jira_context`

Purpose:

- Fetch the latest Jira description and comments.

Actions:

- Call `JiraClient.get_issue_details(issue_key)`.
- Store `description`.
- Store `jira_comments`.

### `parse_agent_context`

Purpose:

- Extract hidden machine-readable context from the Jira description.

Actions:

- Parse the `{code:json}` block.
- Extract `workload_name`.
- Optionally extract `namespace`, `incident_type`, and other future fields if they are added by Discovery.

Failure:

- If `workload_name` cannot be extracted, route to `fail_to_jira`.

### `load_github_context`

Purpose:

- Fetch review feedback from the existing PR if one exists.

Actions:

- Call `GitHubClient.get_pr_comments(branch)`.
- Store `pr_comments`.
- Set `human_feedback = jira_comments + pr_comments`.

### `load_manifest`

Purpose:

- Fetch the current GitOps manifest from the base branch.

Actions:

- Set `file_path = deploy/workloads/{workload_name}.yaml`.
- Call `GitHubClient.get_file_content(file_path, ref=settings.github_base_branch)`.
- Store `original_yaml`.

Failure:

- If the file does not exist, route to `fail_to_jira`.

### `plan_remediation`

Purpose:

- Ask the LLM for a structured remediation plan before rewriting YAML.

Output shape:

```json
{
  "intent": "increase_memory_limit",
  "summary": "Increase the memory limit based on OOMKilled feedback.",
  "changes": [
    {
      "target": "deployment container resources",
      "field": "memory limit",
      "from": "512Mi",
      "to": "1Gi",
      "reason": "Container was OOMKilled and human feedback approved a higher limit."
    }
  ],
  "needs_kubectl_context": true,
  "kubectl_queries": [
    {
      "kind": "deployment",
      "name": "oom-demo",
      "namespace": "k8s-agent-demo",
      "operation": "describe"
    }
  ],
  "risk_level": "low"
}
```

Design notes:

- The plan is advisory, not authoritative.
- Routers and validators must use deterministic checks.
- The LLM should not decide whether validation can be skipped.

### `load_k8s_context`

Purpose:

- Collect bounded read-only Kubernetes context when the plan requests it.

Allowed commands:

```text
kubectl get deployment
kubectl describe deployment
kubectl get pod
kubectl describe pod
kubectl logs
```

Forbidden commands:

```text
kubectl apply
kubectl patch
kubectl delete
kubectl scale
kubectl rollout restart
kubectl exec
kubectl port-forward
```

Design notes:

- This node should be optional.
- It should enforce a strict allowlist independent of the LLM.
- It should require namespace and resource name to come from trusted issue context or parsed manifest context where possible.
- It should truncate output before storing it in graph state.
- If Kubernetes is unavailable, the graph can continue without this context unless the plan explicitly requires it.

### `rewrite_manifest`

Purpose:

- Generate a complete updated YAML manifest.

Inputs:

- `original_yaml`
- `human_feedback`
- `remediation_plan`
- optional `k8s_context`
- optional `validation_errors` from prior attempts

Output:

- `proposed_yaml`

Design notes:

- The model must output only YAML.
- Markdown fences should be stripped defensively.
- Existing `LLMClient.rewrite_yaml` can be adapted first, then upgraded to accept the structured plan.

### `validate_manifest`

Purpose:

- Block malformed or obviously unsafe YAML before GitHub publication.

Initial validation checks:

- YAML parses successfully.
- Manifest is a Kubernetes object.
- `apiVersion`, `kind`, and `metadata.name` are present.
- `metadata.name` should remain consistent with the original manifest.
- The updated object should still contain container definitions for workloads that originally had containers.
- The generated YAML should not be empty.

Important decision:

- Field-level mutation allowlists are intentionally not enforced in the first version. The agent may modify fields beyond memory resources if the LLM and human feedback drive that change.

Rationale:

- This keeps the first LangGraph migration flexible while the demo is still evolving.
- Safety is still provided by deterministic parse checks, Jira visibility, GitHub PR review, and GitOps human approval.
- Field-level allowlists can be added later once desired remediation classes are better defined.

### `self_reflect`

Purpose:

- Give the LLM validation errors and ask it to repair the YAML.

Actions:

- Increment `retry_count`.
- Add validation errors to the rewrite prompt.
- Route back to `rewrite_manifest`.

Limit:

- Retry at most `max_retries`, default `2`.
- After retries are exhausted, route to `fail_to_jira`.

### `publish_pr`

Purpose:

- Write the generated manifest to GitHub and create or update a PR.

Actions:

- Call `GitHubClient.push_file(branch, file_path, proposed_yaml, commit_msg)`.
- Call `GitHubClient.create_or_update_pr(pr_title, pr_body, branch)`.
- Store `pr_url`.

Idempotency:

- Reusing the same branch is expected.
- Existing PRs should be updated, not duplicated.

### `finalize_jira`

Purpose:

- Tell the human reviewer what the agent did and move the issue to review.

Actions:

- Add a Jira comment containing:
  - remediation summary
  - PR URL
  - validation result
  - retry count if applicable
- Transition issue to `In Review`.

### `fail_to_jira`

Purpose:

- Return control to the human through Jira.

Actions:

- Add a Jira comment with:
  - failure reason
  - last validation errors, if any
  - requested human action
- Transition issue back to `To Do`.

This matches the current collaboration pattern: engineers can add a comment, drag or leave the card in `To Do`, and the next polling cycle can resume or rerun the graph.

## Routing

```text
START
-> claim_issue
-> load_jira_context
-> parse_agent_context
   -> fail_to_jira if context invalid
-> load_github_context
-> load_manifest
   -> fail_to_jira if manifest missing
-> plan_remediation
   -> load_k8s_context if needs_kubectl_context
   -> rewrite_manifest otherwise
-> rewrite_manifest
-> validate_manifest
   -> publish_pr if valid
   -> self_reflect if invalid and retry_count < max_retries
   -> fail_to_jira if invalid and retry_count >= max_retries
-> publish_pr
-> finalize_jira
-> END
```

Routers should be deterministic Python functions. The LLM can set fields such as `needs_kubectl_context`, but the graph decides where execution goes based on validated state.

## Human-in-the-loop Strategy

Use Jira as the human-in-the-loop system for the first migration.

Do not introduce LangGraph `interrupt()` in the first version. The current project already has a working human collaboration loop:

```text
To Do = ready for agent action
In Progress = agent is working
In Review = human reviews PR
Jira comments + PR comments = human feedback
```

LangGraph interrupts can be revisited later if the project adds a dedicated UI, ChatOps approval, or explicit approval of high-risk read/write tool calls.

## Kubernetes Tooling Policy

The graph may use read-only Kubernetes context to improve diagnosis and YAML edits.

Allowed:

- Inspect existing deployments, pods, events, and logs.
- Use bounded timeouts.
- Truncate command output.
- Continue without Kubernetes context when unavailable unless the graph marks it as required.

Not allowed:

- Mutating cluster state.
- Running shell commands chosen freely by the LLM.
- Passing untrusted raw command strings directly to a shell.
- Using `kubectl exec`.

Implementation should represent Kubernetes operations as structured requests, not arbitrary command text.

Example:

```python
class KubectlQuery(TypedDict):
    operation: str  # get, describe, logs
    kind: str       # deployment, pod
    namespace: str
    name: str
```

The tool layer maps this structure to an approved command form.

## Testing Strategy

### Unit Tests

- `parse_agent_context` extracts `workload_name` from Jira description.
- `parse_agent_context` routes to failure when context is missing.
- `route_after_plan` chooses `load_k8s_context` only when requested.
- `route_after_validation` chooses publish, reflect, or fail correctly.
- `validate_manifest` catches empty YAML, invalid YAML, missing metadata, and missing containers.

### Graph Tests

- Happy path:
  - fake Jira issue
  - fake GitHub manifest
  - fake LLM YAML
  - graph publishes PR and finalizes Jira

- Missing context:
  - graph comments on Jira and transitions issue back to `To Do`

- Invalid YAML then repaired:
  - first rewrite fails validation
  - self-reflection retries
  - second rewrite passes
  - PR is published

- Invalid YAML after retries:
  - graph fails to Jira and transitions back to `To Do`

- Kubernetes context requested:
  - graph calls only the structured read-only kubectl tool
  - output is stored in truncated form

### Integration Tests

- Celery polling invokes the graph with `thread_id = remediation:{issue_key}`.
- Existing GitHub branch/PR update path remains idempotent.
- Dry-run mode does not perform external writes.

## Implementation Plan

### Phase 1: Graph Skeleton

- Add LangGraph dependencies.
- Add `app/graphs/state.py`.
- Add `app/graphs/remediation.py`.
- Add node modules for Jira, GitHub, LLM, validation, and Kubernetes context.
- Use SQLite checkpointing for local demo.

### Phase 2: Behavior-preserving Migration

- Move current `poll_jira_for_remediation` body into graph nodes.
- Keep external behavior the same:
  - Jira polling schedule unchanged.
  - branch naming unchanged.
  - PR creation/update unchanged.
  - final Jira transition unchanged.

### Phase 3: Structured Planning

- Add `plan_remediation`.
- Update PR body and Jira comments to include the structured plan summary.

### Phase 4: Validation and Self-reflection

- Add deterministic manifest validation.
- Add bounded retry loop.
- Add fail-to-Jira path for unrecoverable validation errors.

### Phase 5: Read-only Kubernetes Context

- Add structured `kubectl` tool.
- Allow the plan to request context.
- Enforce command allowlist outside the LLM.

## Open Future Decisions

- Whether to add field-level mutation allowlists after the initial migration.
- Whether to add incident-type-specific subgraphs.
- Whether to move Discovery Agent into a separate graph.
- Whether to switch checkpointing from SQLite to Postgres.
- Whether to introduce LangGraph interrupts for explicit approvals.
- Whether to add Qdrant for historical incident retrieval after enough closed incidents exist.

