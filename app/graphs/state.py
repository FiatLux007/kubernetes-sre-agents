from __future__ import annotations

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
