# Kubernetes SRE Agents

Open-source Kubernetes reliability agents that detect runtime and configuration issues, deduplicate Jira incidents, and open reviewable GitHub remediation PRs.

## Overview

Kubernetes SRE Agents is an MVP control plane for incident-to-remediation workflows. It connects Kubernetes health signals, Jira ticket operations, GitHub pull requests, MCP-integrated tools, event queues, CI loops, and human-review gates into a reproducible reliability workflow.

The project is designed around three asynchronous agents:

- **Sentinel Agent** detects Kubernetes runtime/configuration issues, collects evidence, fingerprints incidents, and creates or updates deduplicated Jira tickets.
- **Resolver Agent** claims ready Jira tickets, moves them through implementation states, plans remediation, executes tool-calling and test loops, and opens GitHub PRs for infrastructure fixes.
- **Auditor Agent** reviews remediation PRs with lightweight static checks, CI status inspection, risk notes, and human-review handoff.

## Goals

- Detect common Kubernetes reliability issues such as `CrashLoopBackOff`, `ImagePullBackOff`, failed rollouts, unhealthy deployments, and resource-related pod failures.
- Prevent duplicate incident spam by using idempotent event handlers and incident fingerprints.
- Keep remediation reviewable by preferring GitHub PRs over direct production mutations.
- Maintain an auditable trail of agent runs, tool calls, ticket transitions, retries, test results, and PR summaries.
- Support human approval gates before risky actions.

## Architecture

```text
Kubernetes clusters
  -> Sentinel workers
  -> incident event queue
  -> Jira ticket service
  -> work item queue
  -> Resolver workers
  -> GitHub remediation PRs
  -> PR review queue
  -> Auditor workers
```

## Control Plane

The backend control plane is responsible for coordination rather than reasoning. It provides:

- Idempotent event handling
- Retry policies and dead-letter queues
- Agent run state transitions
- Incident fingerprinting and deduplication
- Audit logs for tool calls and decisions
- Typed adapters for Kubernetes, Jira, and GitHub
- Human-review gates for remediation workflows

## MVP Workflow

1. Sentinel scans Kubernetes workloads and detects a health issue.
2. Sentinel computes an incident fingerprint and checks whether an open Jira ticket already exists.
3. If no open ticket exists, Sentinel creates a Jira issue with symptoms, affected resources, evidence, probable root cause, and suggested next steps.
4. Resolver polls Jira for tickets in `Ready to Start`, claims one, transitions it to `In Progress`, and writes an implementation plan.
5. Resolver executes a tool-calling loop, applies code or infrastructure changes, runs validation, and opens a GitHub PR.
6. Resolver writes a final summary to Jira and moves the ticket to `Ready for Review`.
7. Auditor reviews the PR, runs lightweight checks, summarizes risk, and leaves a GitHub review comment.

## Planned Stack

- Python 3.12+
- FastAPI
- Pydantic
- PostgreSQL
- Redis-backed event queues
- Kubernetes Python client
- Jira MCP integration
- GitHub MCP integration
- OpenTelemetry
- GitHub Actions

## Status

This repository is currently an early MVP scaffold. The first implementation target is an end-to-end demo for Kubernetes incident detection, Jira ticket creation, ticket-driven remediation planning, GitHub PR creation, and lightweight PR review.
