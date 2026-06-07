class FakeJira:
    def __init__(self, settings):
        self.settings = settings

    def search_issues(self, jql):
        self.jql = jql
        return [{"key": "KAN-1"}, {"key": "KAN-2"}]


def test_poll_jira_for_remediation_invokes_graph(monkeypatch):
    from app import worker

    calls = []

    def fake_jira_client(settings):
        client = FakeJira(settings)
        calls.append(("jira", client))
        return client

    def fake_run_remediation(issue_key, issue_url, settings, *, jira=None):
        calls.append(("graph", issue_key, issue_url, jira))
        status = "success" if issue_key == "KAN-1" else "failed"
        return {"status": status, "thread_id": f"remediation:{issue_key}", "state": {}}

    monkeypatch.setattr("app.clients.jira.JiraClient", fake_jira_client)
    monkeypatch.setattr("app.graphs.remediation.run_remediation", fake_run_remediation)

    result = worker.poll_jira_for_remediation()

    assert result == {"status": "success", "processed": 1, "failed": 1}
    assert calls[0][0] == "jira"
    assert calls[1][1:3] == ("KAN-1", "/browse/KAN-1")
    assert calls[2][1:3] == ("KAN-2", "/browse/KAN-2")
