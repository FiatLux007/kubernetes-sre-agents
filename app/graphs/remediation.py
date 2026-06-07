from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import subprocess
from typing import Any

import yaml
from langgraph.graph import END, START, StateGraph

from app.clients.github import GitHubClient
from app.clients.jira import JiraClient
from app.clients.llm import LLMClient
from app.config import Settings
from app.schemas import JiraIssue
from app.graphs.state import RemediationState

logger = logging.getLogger(__name__)

ALLOWED_KUBECTL_OPERATIONS = {"get", "describe", "logs"}
ALLOWED_KUBECTL_KINDS = {"deployment", "pod"}
MAX_K8S_CONTEXT_CHARS = 4000


def build_remediation_graph(
    settings: Settings,
    *,
    jira: JiraClient | None = None,
    github: GitHubClient | None = None,
    llm: LLMClient | None = None,
    k8s_tool: Any | None = None,
    checkpointer: Any | None = None,
):
    jira = jira or JiraClient(settings)
    github = github or GitHubClient(settings)
    llm = llm or LLMClient(settings)
    k8s_tool = k8s_tool or KubectlTool(settings)

    graph = StateGraph(RemediationState)
    graph.add_node("claim_issue", lambda state: claim_issue(state, settings, jira))
    graph.add_node("load_jira_context", lambda state: load_jira_context(state, jira))
    graph.add_node("parse_agent_context", parse_agent_context)
    graph.add_node("load_github_context", lambda state: load_github_context(state, github))
    graph.add_node("load_manifest", lambda state: load_manifest(state, settings, github))
    graph.add_node("plan_remediation", lambda state: plan_remediation(state, llm))
    graph.add_node("load_k8s_context", lambda state: load_k8s_context(state, k8s_tool))
    graph.add_node("rewrite_manifest", lambda state: rewrite_manifest(state, llm))
    graph.add_node("validate_manifest", validate_manifest)
    graph.add_node("self_reflect", self_reflect)
    graph.add_node("publish_pr", lambda state: publish_pr(state, github))
    graph.add_node("finalize_jira", lambda state: finalize_jira(state, jira))
    graph.add_node("fail_to_jira", lambda state: fail_to_jira(state, jira))

    graph.add_edge(START, "claim_issue")
    graph.add_edge("claim_issue", "load_jira_context")
    graph.add_edge("load_jira_context", "parse_agent_context")
    graph.add_conditional_edges(
        "parse_agent_context",
        route_after_context,
        {"continue": "load_github_context", "fail": "fail_to_jira"},
    )
    graph.add_edge("load_github_context", "load_manifest")
    graph.add_conditional_edges(
        "load_manifest",
        route_after_manifest,
        {"continue": "plan_remediation", "fail": "fail_to_jira"},
    )
    graph.add_conditional_edges(
        "plan_remediation",
        route_after_plan,
        {"k8s_context": "load_k8s_context", "rewrite": "rewrite_manifest"},
    )
    graph.add_edge("load_k8s_context", "rewrite_manifest")
    graph.add_edge("rewrite_manifest", "validate_manifest")
    graph.add_conditional_edges(
        "validate_manifest",
        route_after_validation,
        {"publish": "publish_pr", "reflect": "self_reflect", "fail": "fail_to_jira"},
    )
    graph.add_edge("self_reflect", "rewrite_manifest")
    graph.add_edge("publish_pr", "finalize_jira")
    graph.add_edge("finalize_jira", END)
    graph.add_edge("fail_to_jira", END)

    return graph.compile(checkpointer=checkpointer)


def run_remediation(
    issue_key: str,
    issue_url: str,
    settings: Settings,
    *,
    jira: JiraClient | None = None,
    github: GitHubClient | None = None,
    llm: LLMClient | None = None,
    k8s_tool: Any | None = None,
    checkpointer: Any | None = None,
) -> dict[str, Any]:
    jira = jira or JiraClient(settings)
    owns_checkpointer = checkpointer is None
    conn: sqlite3.Connection | None = None
    if owns_checkpointer:
        from langgraph.checkpoint.sqlite import SqliteSaver

        checkpoint_dir = os.path.dirname(settings.langgraph_checkpoint_path)
        if checkpoint_dir:
            os.makedirs(checkpoint_dir, exist_ok=True)
        conn = sqlite3.connect(settings.langgraph_checkpoint_path, check_same_thread=False)
        checkpointer = SqliteSaver(conn)

    try:
        graph = build_remediation_graph(
            settings,
            jira=jira,
            github=github,
            llm=llm,
            k8s_tool=k8s_tool,
            checkpointer=checkpointer,
        )
        config = {"configurable": {"thread_id": remediation_thread_id(issue_key)}}
        result = graph.invoke({"issue_key": issue_key, "issue_url": issue_url}, config=config)
        return {
            "status": "success" if result.get("pr_url") else "failed",
            "thread_id": remediation_thread_id(issue_key),
            "state": result,
        }
    except Exception as exc:
        logger.exception("remediation.graph_failed issue=%s", issue_key)
        issue = JiraIssue(key=issue_key, url=issue_url)
        jira.add_comment(issue, f"## Auto-remediation failed\n\nUnexpected graph error: {exc}")
        jira.transition_issue(issue, "To Do")
        return {
            "status": "failed",
            "thread_id": remediation_thread_id(issue_key),
            "state": {"issue_key": issue_key, "issue_url": issue_url, "failure_reason": str(exc)},
        }
    finally:
        if conn is not None:
            conn.close()


def remediation_thread_id(issue_key: str) -> str:
    return f"remediation:{issue_key}"


def claim_issue(state: RemediationState, settings: Settings, jira: JiraClient) -> RemediationState:
    issue = _issue(state, settings)
    jira.transition_issue(issue, "In Progress")
    issue_key = state["issue_key"]
    return {
        "branch": f"ai-fix/{issue_key.lower()}",
        "retry_count": state.get("retry_count", 0),
        "max_retries": state.get("max_retries", 2),
    }


def load_jira_context(state: RemediationState, jira: JiraClient) -> RemediationState:
    details = jira.get_issue_details(state["issue_key"])
    return {
        "description": details.get("description", ""),
        "jira_comments": details.get("comments", []),
    }


def parse_agent_context(state: RemediationState) -> RemediationState:
    context = parse_agent_context_from_description(state.get("description", ""))
    workload_name = context.get("workload_name")
    if not workload_name:
        return {"failure_reason": "could not extract workload_name from issue description"}

    update: RemediationState = {"workload_name": workload_name}
    namespace = context.get("namespace")
    if namespace:
        update["namespace"] = namespace
    return update


def parse_agent_context_from_description(description: str) -> dict[str, Any]:
    match = re.search(r"\{code:json\}(.*?)\{code\}", description or "", re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(1).strip())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def load_github_context(state: RemediationState, github: GitHubClient) -> RemediationState:
    pr_comments = github.get_pr_comments(state["branch"])
    jira_comments = state.get("jira_comments", [])
    return {"pr_comments": pr_comments, "human_feedback": jira_comments + pr_comments}


def load_manifest(state: RemediationState, settings: Settings, github: GitHubClient) -> RemediationState:
    file_path = f"deploy/workloads/{state['workload_name']}.yaml"
    original_yaml, _ = github.get_file_content(file_path, ref=settings.github_base_branch)
    if not original_yaml:
        return {"file_path": file_path, "failure_reason": f"file {file_path} not found in repo"}
    return {"file_path": file_path, "original_yaml": original_yaml}


def plan_remediation(state: RemediationState, llm: LLMClient) -> RemediationState:
    plan = llm.plan_remediation(
        state.get("original_yaml", ""),
        state.get("human_feedback", []),
        issue_key=state["issue_key"],
        workload_name=state["workload_name"],
    )
    return {"remediation_plan": plan}


def load_k8s_context(state: RemediationState, k8s_tool: Any) -> RemediationState:
    plan = state.get("remediation_plan", {})
    queries = plan.get("kubectl_queries", []) if isinstance(plan, dict) else []
    outputs: list[dict[str, Any]] = []
    for query in queries:
        try:
            outputs.append(k8s_tool.run(query))
        except Exception as exc:
            outputs.append({"query": query, "error": str(exc)})
    return {"k8s_context": {"queries": outputs}}


def rewrite_manifest(state: RemediationState, llm: LLMClient) -> RemediationState:
    proposed_yaml = llm.rewrite_yaml(
        state.get("original_yaml", ""),
        state.get("human_feedback", []),
        remediation_plan=state.get("remediation_plan", {}),
        k8s_context=state.get("k8s_context", {}),
        validation_errors=state.get("validation_errors", []),
    )
    return {"proposed_yaml": proposed_yaml}


def validate_manifest(state: RemediationState) -> RemediationState:
    passed, errors = validate_kubernetes_manifest(state.get("original_yaml", ""), state.get("proposed_yaml", ""))
    return {"validation_passed": passed, "validation_errors": errors}


def self_reflect(state: RemediationState) -> RemediationState:
    return {"retry_count": state.get("retry_count", 0) + 1}


def publish_pr(state: RemediationState, github: GitHubClient) -> RemediationState:
    issue_key = state["issue_key"]
    workload_name = state["workload_name"]
    pr_title = f"[{issue_key}] Remediation for {workload_name}"
    plan_summary = state.get("remediation_plan", {}).get("summary", "Iterative remediation generated by K8s-Agent.")
    pr_body = (
        "Iterative remediation generated by K8s-Agent based on human feedback.\n\n"
        f"Plan: {plan_summary}"
    )
    commit_msg = f"[{issue_key}] Auto-remediation update for {workload_name}"
    github.push_file(state["branch"], state["file_path"], state["proposed_yaml"], commit_msg)
    pr = github.create_or_update_pr(pr_title, pr_body, state["branch"])
    return {"pr_title": pr.title, "pr_url": pr.url}


def finalize_jira(state: RemediationState, jira: JiraClient) -> RemediationState:
    issue = JiraIssue(key=state["issue_key"], url=state["issue_url"])
    plan_summary = state.get("remediation_plan", {}).get("summary", "Remediation update generated.")
    retry_count = state.get("retry_count", 0)
    comment = (
        "## Agent Iteration Complete\n\n"
        f"{plan_summary}\n\n"
        f"Validation: passed\n"
        f"Retries: {retry_count}\n"
        f"PR: {state.get('pr_url', '')}"
    )
    jira.add_comment(issue, comment)
    jira.transition_issue(issue, "In Review")
    return {"jira_status": "In Review"}


def fail_to_jira(state: RemediationState, jira: JiraClient) -> RemediationState:
    issue = JiraIssue(key=state["issue_key"], url=state["issue_url"])
    reason = state.get("failure_reason") or "manifest validation failed"
    errors = state.get("validation_errors", [])
    error_text = "\n".join(f"- {error}" for error in errors) if errors else "- No validation errors captured."
    comment = (
        "## Auto-remediation failed\n\n"
        f"Reason: {reason}\n\n"
        f"Validation errors:\n{error_text}\n\n"
        "Please add guidance in Jira comments and leave the issue in To Do for the next polling cycle."
    )
    jira.add_comment(issue, comment)
    jira.transition_issue(issue, "To Do")
    return {"jira_status": "To Do", "next_action": "human_feedback_required"}


def route_after_context(state: RemediationState) -> str:
    return "fail" if state.get("failure_reason") else "continue"


def route_after_manifest(state: RemediationState) -> str:
    return "fail" if state.get("failure_reason") else "continue"


def route_after_plan(state: RemediationState) -> str:
    plan = state.get("remediation_plan", {})
    if isinstance(plan, dict) and plan.get("needs_kubectl_context") and plan.get("kubectl_queries"):
        return "k8s_context"
    return "rewrite"


def route_after_validation(state: RemediationState) -> str:
    if state.get("validation_passed"):
        return "publish"
    if state.get("retry_count", 0) < state.get("max_retries", 2):
        return "reflect"
    return "fail"


def validate_kubernetes_manifest(original_yaml: str, proposed_yaml: str) -> tuple[bool, list[str]]:
    errors: list[str] = []
    original = _load_yaml_document(original_yaml, "original", errors)
    proposed = _load_yaml_document(proposed_yaml, "proposed", errors)
    if errors:
        return False, errors

    if not isinstance(proposed, dict):
        errors.append("proposed YAML must be a Kubernetes object")
        return False, errors

    for field in ("apiVersion", "kind"):
        if not proposed.get(field):
            errors.append(f"proposed manifest missing {field}")

    metadata = proposed.get("metadata")
    if not isinstance(metadata, dict) or not metadata.get("name"):
        errors.append("proposed manifest missing metadata.name")

    if isinstance(original, dict):
        original_name = _metadata_name(original)
        proposed_name = _metadata_name(proposed)
        if original_name and proposed_name and original_name != proposed_name:
            errors.append("metadata.name must remain unchanged")

        if _has_containers(original) and not _has_containers(proposed):
            errors.append("proposed manifest must preserve workload container definitions")

    return not errors, errors


def _load_yaml_document(raw_yaml: str, label: str, errors: list[str]) -> Any:
    if not raw_yaml or not raw_yaml.strip():
        errors.append(f"{label} YAML is empty")
        return None
    try:
        document = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        errors.append(f"{label} YAML is invalid: {exc}")
        return None
    if document is None:
        errors.append(f"{label} YAML is empty")
    return document


def _metadata_name(document: dict[str, Any]) -> str:
    metadata = document.get("metadata", {})
    return metadata.get("name", "") if isinstance(metadata, dict) else ""


def _has_containers(document: dict[str, Any]) -> bool:
    containers = (
        document.get("spec", {})
        .get("template", {})
        .get("spec", {})
        .get("containers")
    )
    return isinstance(containers, list) and bool(containers)


def _issue(state: RemediationState, settings: Settings) -> JiraIssue:
    issue_key = state["issue_key"]
    issue_url = state.get("issue_url") or f"{settings.jira_base_url}/browse/{issue_key}"
    return JiraIssue(key=issue_key, url=issue_url)


class KubectlTool:
    def __init__(self, settings: Settings):
        self.settings = settings

    def run(self, query: dict[str, Any]) -> dict[str, Any]:
        operation = query.get("operation")
        kind = query.get("kind")
        namespace = query.get("namespace")
        name = query.get("name")

        if operation not in ALLOWED_KUBECTL_OPERATIONS:
            raise ValueError(f"kubectl operation not allowed: {operation}")
        if operation != "logs" and kind not in ALLOWED_KUBECTL_KINDS:
            raise ValueError(f"kubectl kind not allowed: {kind}")
        if not name:
            raise ValueError("kubectl query requires name")

        cmd = ["kubectl"]
        if operation == "logs":
            cmd.extend(["logs", name])
        elif operation == "get":
            cmd.extend(["get", kind, name, "-o", "yaml"])
        else:
            cmd.extend(["describe", kind, name])
        if namespace:
            cmd.extend(["-n", namespace])

        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=self.settings.kubectl_timeout_seconds,
        )
        output = completed.stdout if completed.returncode == 0 else completed.stderr
        return {
            "query": query,
            "returncode": completed.returncode,
            "output": output[:MAX_K8S_CONTEXT_CHARS],
        }
