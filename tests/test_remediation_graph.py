import pytest

from app.config import Settings
from app.graphs.remediation import (
    KubectlTool,
    build_remediation_graph,
    parse_agent_context_from_description,
    route_after_plan,
    route_after_validation,
    validate_kubernetes_manifest,
)
from app.schemas import PullRequest


VALID_DESCRIPTION = """
Incident details

{code:json}
{"workload_name": "oom-demo", "namespace": "k8s-agent-demo"}
{code}
"""

VALID_YAML = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: oom-demo
spec:
  template:
    spec:
      containers:
        - name: app
          image: busybox
          resources:
            limits:
              memory: 128Mi
"""

UPDATED_YAML = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: oom-demo
spec:
  template:
    spec:
      containers:
        - name: app
          image: busybox
          resources:
            limits:
              memory: 256Mi
"""


class FakeJira:
    def __init__(self, description=VALID_DESCRIPTION, comments=None):
        self.description = description
        self.comments = comments or ["please increase memory"]
        self.added_comments = []
        self.transitions = []

    def get_issue_details(self, issue_key):
        return {"description": self.description, "comments": self.comments}

    def add_comment(self, issue, comment):
        self.added_comments.append((issue.key, comment))

    def transition_issue(self, issue, status_name):
        self.transitions.append((issue.key, status_name))


class FakeGitHub:
    def __init__(self, original_yaml=VALID_YAML, pr_comments=None):
        self.original_yaml = original_yaml
        self.pr_comments = pr_comments or []
        self.pushed = []
        self.prs = []

    def get_pr_comments(self, branch):
        return self.pr_comments

    def get_file_content(self, file_path, ref=None):
        return self.original_yaml, "sha" if self.original_yaml else ""

    def push_file(self, branch, file_path, content, commit_msg):
        self.pushed.append((branch, file_path, content, commit_msg))

    def create_or_update_pr(self, title, body, branch):
        self.prs.append((title, body, branch))
        return PullRequest(title=title, branch=branch, url=f"https://github.test/pull/{len(self.prs)}")


class FakeLLM:
    def __init__(self, rewrites=None, plan=None):
        self.rewrites = list(rewrites or [UPDATED_YAML])
        self.plan = plan or {
            "intent": "increase_memory_limit",
            "summary": "Increase memory limit.",
            "changes": [],
            "needs_kubectl_context": False,
            "kubectl_queries": [],
            "risk_level": "low",
        }
        self.rewrite_calls = []

    def plan_remediation(self, original_yaml, human_comments, *, issue_key, workload_name):
        return self.plan

    def rewrite_yaml(self, original_yaml, human_comments, *, remediation_plan=None, k8s_context=None, validation_errors=None):
        self.rewrite_calls.append(
            {
                "remediation_plan": remediation_plan,
                "k8s_context": k8s_context,
                "validation_errors": validation_errors,
            }
        )
        if len(self.rewrites) > 1:
            return self.rewrites.pop(0)
        return self.rewrites[0]


class FakeK8sTool:
    def __init__(self):
        self.queries = []

    def run(self, query):
        self.queries.append(query)
        return {"query": query, "returncode": 0, "output": "deployment details"}


def invoke_graph(jira, github, llm, k8s_tool=None):
    settings = Settings(dry_run=True)
    graph = build_remediation_graph(settings, jira=jira, github=github, llm=llm, k8s_tool=k8s_tool or FakeK8sTool())
    return graph.invoke(
        {"issue_key": "KAN-1", "issue_url": "https://jira.test/browse/KAN-1"},
        config={"configurable": {"thread_id": "remediation:KAN-1"}},
    )


def test_parse_agent_context_from_description():
    context = parse_agent_context_from_description(VALID_DESCRIPTION)

    assert context["workload_name"] == "oom-demo"
    assert context["namespace"] == "k8s-agent-demo"


def test_parse_agent_context_missing_json_returns_empty():
    assert parse_agent_context_from_description("no json here") == {}


def test_route_after_plan():
    assert route_after_plan({"remediation_plan": {"needs_kubectl_context": False}}) == "rewrite"
    assert route_after_plan(
        {
            "remediation_plan": {
                "needs_kubectl_context": True,
                "kubectl_queries": [{"operation": "describe", "kind": "deployment", "name": "oom-demo"}],
            }
        }
    ) == "k8s_context"


def test_route_after_validation():
    assert route_after_validation({"validation_passed": True}) == "publish"
    assert route_after_validation({"validation_passed": False, "retry_count": 0, "max_retries": 2}) == "reflect"
    assert route_after_validation({"validation_passed": False, "retry_count": 2, "max_retries": 2}) == "fail"


def test_validate_manifest_rejects_invalid_cases():
    assert validate_kubernetes_manifest(VALID_YAML, "")[0] is False
    assert validate_kubernetes_manifest(VALID_YAML, "not: [")[0] is False
    assert validate_kubernetes_manifest(VALID_YAML, "kind: Deployment")[0] is False
    no_containers = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: oom-demo
spec: {}
"""
    passed, errors = validate_kubernetes_manifest(VALID_YAML, no_containers)
    assert passed is False
    assert "container" in " ".join(errors)


@pytest.mark.parametrize("operation", ["apply", "patch", "delete", "scale", "exec"])
def test_kubectl_tool_rejects_forbidden_operations(operation):
    tool = KubectlTool(Settings())

    with pytest.raises(ValueError):
        tool.run({"operation": operation, "kind": "deployment", "namespace": "default", "name": "oom-demo"})


def test_graph_happy_path_publishes_pr_and_moves_jira_to_review():
    jira = FakeJira()
    github = FakeGitHub()
    llm = FakeLLM()

    result = invoke_graph(jira, github, llm)

    assert result["pr_url"] == "https://github.test/pull/1"
    assert github.pushed[0][0] == "ai-fix/kan-1"
    assert jira.transitions == [("KAN-1", "In Progress"), ("KAN-1", "In Review")]


def test_graph_missing_context_fails_to_jira_todo():
    jira = FakeJira(description="no machine context")
    github = FakeGitHub()
    llm = FakeLLM()

    result = invoke_graph(jira, github, llm)

    assert result["jira_status"] == "To Do"
    assert not github.pushed
    assert jira.transitions == [("KAN-1", "In Progress"), ("KAN-1", "To Do")]
    assert "workload_name" in jira.added_comments[-1][1]


def test_graph_missing_manifest_fails_to_jira_todo():
    jira = FakeJira()
    github = FakeGitHub(original_yaml="")
    llm = FakeLLM()

    result = invoke_graph(jira, github, llm)

    assert result["jira_status"] == "To Do"
    assert not github.pushed
    assert "not found" in jira.added_comments[-1][1]


def test_graph_invalid_yaml_then_repaired_publishes_pr():
    jira = FakeJira()
    github = FakeGitHub()
    llm = FakeLLM(rewrites=["not: [", UPDATED_YAML])

    result = invoke_graph(jira, github, llm)

    assert result["pr_url"] == "https://github.test/pull/1"
    assert result["retry_count"] == 1
    assert len(llm.rewrite_calls) == 2
    assert llm.rewrite_calls[-1]["validation_errors"]


def test_graph_invalid_yaml_after_retries_fails_to_jira():
    jira = FakeJira()
    github = FakeGitHub()
    llm = FakeLLM(rewrites=["not: ["])

    result = invoke_graph(jira, github, llm)

    assert result["jira_status"] == "To Do"
    assert result["retry_count"] == 2
    assert not github.pushed
    assert jira.transitions[-1] == ("KAN-1", "To Do")


def test_graph_loads_k8s_context_when_plan_requests_it():
    plan = {
        "intent": "inspect_deployment",
        "summary": "Inspect deployment before rewrite.",
        "changes": [],
        "needs_kubectl_context": True,
        "kubectl_queries": [{"operation": "describe", "kind": "deployment", "namespace": "default", "name": "oom-demo"}],
        "risk_level": "low",
    }
    jira = FakeJira()
    github = FakeGitHub()
    llm = FakeLLM(plan=plan)
    k8s_tool = FakeK8sTool()

    result = invoke_graph(jira, github, llm, k8s_tool=k8s_tool)

    assert result["k8s_context"]["queries"][0]["output"] == "deployment details"
    assert k8s_tool.queries == plan["kubectl_queries"]
    assert llm.rewrite_calls[0]["k8s_context"]["queries"][0]["output"] == "deployment details"
