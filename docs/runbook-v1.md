# Runbook V1

## OOMKilled

Expected flow:

```text
Robusta event
-> K8s-Agent webhook
-> Redis dedupe
-> Worker diagnosis
-> memory policy check
-> dry-run Jira issue/comment
-> dry-run PR recommendation
```

Human review should check:

- whether the workload recently deployed
- whether memory usage increased gradually, suggesting a leak
- whether the proposed limit fits namespace quota
- whether request/limit ratios remain sane

## CrashLoopBackOff

Expected flow:

```text
Robusta event
-> K8s-Agent webhook
-> Redis dedupe
-> Worker diagnosis
-> dry-run Jira issue/comment
-> no PR recommendation
```

Human review should check:

- image pull and startup command
- missing environment variables
- ConfigMap/Secret references
- dependency readiness
- recent deployment changes

## Duplicate Alerts

Redis dedupe uses a workload fingerprint. A repeated alert within `DEDUPE_TTL_SECONDS` does not create a second incident task.

