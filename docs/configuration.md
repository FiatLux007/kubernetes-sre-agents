# Configuration

Configuration is read from environment variables. For local demo usage, copy:

```bash
cp .env.example .env
```

## Core

```text
APP_ENV=local
DRY_RUN=true
TASK_ALWAYS_EAGER=false
```

`DRY_RUN=true` means:

- no real Jira issue is created
- no real GitHub PR is created
- no real LLM call is made

## Redis and Celery

```text
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
```

## LLM

```text
LLM_PROVIDER=
LLM_API_KEY=
LLM_MODEL=
```

V1 ships with a dry-run adapter. Add real integration later through the `LLMClient` adapter.

## Jira

```text
JIRA_BASE_URL=
JIRA_PROJECT_KEY=SRE
JIRA_API_TOKEN=
JIRA_USER_EMAIL=
```

V1 ships with a dry-run adapter. Add real HTTP or MCP integration later through the `JiraClient` adapter.

## GitHub

```text
GITHUB_TOKEN=
GITHUB_OWNER=
GITHUB_REPO=
GITHUB_BASE_BRANCH=main
```

V1 ships with a dry-run adapter. Add real HTTP or MCP integration later through the `GitHubClient` adapter.

## Policy

```text
MAX_MEMORY_LIMIT_GI=4
DEDUPE_TTL_SECONDS=300
```

OOM recommendations are blocked if they exceed the configured memory limit ceiling.

