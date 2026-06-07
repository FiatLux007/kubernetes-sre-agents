from app.agent import handle_incident
from app.config import Settings


class FakeJira:
    def __init__(self):
        self.created = []
        self.comments = []

    def create_issue(self, incident, decision):
        from app.schemas import JiraIssue

        key = f"KAN-{len(self.created) + 1}"
        self.created.append((incident, decision))
        return JiraIssue(key=key, url=f"https://jira.test/browse/{key}")

    def add_comment(self, issue, comment):
        self.comments.append((issue.key, comment))


class FakeLLM:
    def __init__(self, settings):
        self.settings = settings

    def generate_diagnosis(self, incident, decision):
        return decision.summary


class ContendedRedis:
    def __init__(self):
        self.values = {}
        self.expirations = {}
        self.deleted = []

    def get(self, key):
        if key == "active_issue:k8s-agent-demo:oom-demo":
            return "KAN-1"
        return self.values.get(key)

    def set(self, key, value, nx=False, ex=None):
        if nx and key == "active_issue:k8s-agent-demo:oom-demo:lock":
            return False
        self.values[key] = value
        return True

    def setex(self, key, ttl, value):
        self.values[key] = value
        self.expirations[key] = ttl

    def expire(self, key, ttl):
        self.expirations[key] = ttl

    def delete(self, key):
        self.deleted.append(key)


def test_handle_incident_waits_for_existing_issue_when_correlation_lock_is_held(monkeypatch):
    jira = FakeJira()
    monkeypatch.setattr("app.agent.JiraClient", lambda settings: jira)
    monkeypatch.setattr("app.agent.LLMClient", FakeLLM)

    payload = {
        "title": "OOMKilled / CrashLoopBackOff event: oom-demo-7ff6fc9987-t5k8v",
        "cluster_name": "k3s-k8s-agent-demo",
        "aggregation_key": "k8s-agent-demo",
        "service": {"name": "oom-demo", "namespace": "k8s-agent-demo", "resource_type": "Deployment"},
        "subject": {
            "name": "oom-demo-7ff6fc9987-t5k8v",
            "kind": "pod",
            "namespace": "k8s-agent-demo",
            "labels": {"app": "oom-demo", "memory_limit": "32Mi"},
        },
    }

    result = handle_incident(payload, Settings(dry_run=False, jira_base_url="https://jira.test"), ContendedRedis())

    assert result["issue"]["key"] == "KAN-1"
    assert result["is_appended"] is True
    assert jira.created == []
    assert jira.comments
    assert "Subsequent Incident Detected" in jira.comments[0][1]
