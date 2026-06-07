import logging
from uuid import uuid4

import httpx

from app.config import Settings
from app.schemas import AgentDecision, IncidentPayload, JiraIssue

logger = logging.getLogger(__name__)


class JiraClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        if self.settings.jira_user_email and self.settings.jira_api_token:
            self.auth = (self.settings.jira_user_email, self.settings.jira_api_token)
        else:
            self.auth = None
        self.headers = {"Accept": "application/json", "Content-Type": "application/json"}

    def create_issue(self, incident: IncidentPayload, decision: AgentDecision) -> JiraIssue:
        if self.settings.dry_run or not self.auth:
            key = f"DRYRUN-{str(uuid4())[:8].upper()}"
            logger.info("dry_run.jira create_issue key=%s summary=%s", key, decision.summary)
            return JiraIssue(key=key, url=f"dry-run://jira/{key}")
        
        url = f"{self.settings.jira_base_url}/rest/api/2/issue"
        import json
        agent_context = json.dumps({"workload_name": incident.workload_name})
        desc = f"Incident: {incident.alert_name}\nReason: {incident.reason}\n\nDiagnosis:\n{decision.llm_diagnosis}\n\nEvidence:\n" + "\n".join(decision.evidence)
        desc += f"\n\n{{code:json}}\n{agent_context}\n{{code}}"

        payload = {
            "fields": {
                "project": {"key": self.settings.jira_project_key},
                "summary": decision.summary[:255],
                "description": desc,
                "issuetype": {"name": "Task"},
                "labels": ["AI-Remediation"]
            }
        }
        try:
            response = httpx.post(url, json=payload, auth=self.auth, headers=self.headers, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            return JiraIssue(key=data["key"], url=f"{self.settings.jira_base_url}/browse/{data['key']}")
        except httpx.HTTPError as e:
            logger.error("Failed to create Jira issue: %s. Response: %s", e, e.response.text if hasattr(e, "response") and e.response else "No response")
            key = f"{self.settings.jira_project_key}-ERROR"
            return JiraIssue(key=key, url=f"{self.settings.jira_base_url}/browse/{key}")

    def add_comment(self, issue: JiraIssue, comment: str) -> None:
        if self.settings.dry_run or not self.auth or issue.key.startswith("DRYRUN") or issue.key.endswith("-ERROR"):
            logger.info("dry_run.jira add_comment key=%s comment=%s", issue.key, comment.replace("\n", " ")[:500])
            return
        
        url = f"{self.settings.jira_base_url}/rest/api/2/issue/{issue.key}/comment"
        payload = {"body": comment}
        try:
            response = httpx.post(url, json=payload, auth=self.auth, headers=self.headers, timeout=10.0)
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.error("Failed to add Jira comment: %s", e)

    def transition_issue(self, issue: JiraIssue, status_name: str) -> None:
        if self.settings.dry_run or not self.auth or issue.key.startswith("DRYRUN") or issue.key.endswith("-ERROR"):
            logger.info("dry_run.jira transition_issue key=%s to status=%s", issue.key, status_name)
            return

        # 1. Fetch available transitions
        url_get = f"{self.settings.jira_base_url}/rest/api/2/issue/{issue.key}/transitions"
        try:
            resp = httpx.get(url_get, auth=self.auth, headers=self.headers, timeout=10.0)
            resp.raise_for_status()
            transitions = resp.json().get("transitions", [])
        except httpx.HTTPError as e:
            logger.error("Failed to fetch transitions for %s: %s", issue.key, e)
            return

        # 2. Find the transition ID by matching the name
        target_id = None
        for t in transitions:
            if t["name"].lower() == status_name.lower() or t.get("to", {}).get("name", "").lower() == status_name.lower():
                target_id = t["id"]
                break

        if not target_id:
            logger.warning("No transition found matching '%s' for issue %s. Available: %s", status_name, issue.key, [t["name"] for t in transitions])
            return

        # 3. Perform the transition
        url_post = url_get
        payload = {"transition": {"id": target_id}}
        try:
            resp_post = httpx.post(url_post, json=payload, auth=self.auth, headers=self.headers, timeout=10.0)
            resp_post.raise_for_status()
            logger.info("Successfully transitioned %s to %s", issue.key, status_name)
        except httpx.HTTPError as e:
            logger.error("Failed to transition %s to %s: %s", issue.key, status_name, e)

    def search_issues(self, jql: str) -> list[dict]:
        if self.settings.dry_run or not self.auth:
            return []
        
        url = f"{self.settings.jira_base_url}/rest/api/2/search/jql"
        params = {"jql": jql, "maxResults": 50, "fields": "summary,description,status"}
        try:
            resp = httpx.get(url, params=params, auth=self.auth, headers=self.headers, timeout=10.0)
            resp.raise_for_status()
            return resp.json().get("issues", [])
        except httpx.HTTPError as e:
            logger.error("Failed to search Jira issues: %s", e)
            return []

    def get_issue_details(self, issue_key: str) -> dict:
        if self.settings.dry_run or not self.auth:
            return {"description": "", "comments": []}
            
        url = f"{self.settings.jira_base_url}/rest/api/2/issue/{issue_key}"
        params = {"fields": "description,comment"}
        try:
            resp = httpx.get(url, params=params, auth=self.auth, headers=self.headers, timeout=10.0)
            resp.raise_for_status()
            data = resp.json().get("fields", {})
            desc = data.get("description", "")
            comments = [c["body"] for c in data.get("comment", {}).get("comments", [])]
            return {"description": desc, "comments": comments}
        except httpx.HTTPError as e:
            logger.error("Failed to fetch Jira issue details for %s: %s", issue_key, e)
            return {"description": "", "comments": []}

