import base64
import logging
import httpx
from datetime import datetime

from app.config import Settings
from app.schemas import AgentDecision, IncidentPayload, PullRequest

logger = logging.getLogger(__name__)


class GitHubClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = "https://api.github.com"
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        if self.settings.github_token:
            self.headers["Authorization"] = f"Bearer {self.settings.github_token}"
            
        self.owner = self.settings.github_owner
        self.repo = self.settings.github_repo
        self.base_branch = self.settings.github_base_branch

    def _get_base_url(self) -> str:
        return f"{self.base_url}/repos/{self.owner}/{self.repo}"

    def get_file_content(self, file_path: str, ref: str = None) -> tuple[str, str]:
        if not ref:
            ref = self.base_branch
        url = f"{self._get_base_url()}/contents/{file_path}?ref={ref}"
        resp = httpx.get(url, headers=self.headers)
        if resp.status_code == 404:
            return "", ""
        resp.raise_for_status()
        data = resp.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, data["sha"]

    def ensure_branch(self, branch: str) -> None:
        """Creates branch if it does not exist"""
        url = f"{self._get_base_url()}/git/ref/heads/{branch}"
        resp = httpx.get(url, headers=self.headers)
        if resp.status_code == 200:
            return  # branch exists
        
        # Get base sha
        ref_resp = httpx.get(f"{self._get_base_url()}/git/ref/heads/{self.base_branch}", headers=self.headers)
        ref_resp.raise_for_status()
        base_sha = ref_resp.json()["object"]["sha"]

        branch_resp = httpx.post(
            f"{self._get_base_url()}/git/refs",
            headers=self.headers,
            json={"ref": f"refs/heads/{branch}", "sha": base_sha}
        )
        branch_resp.raise_for_status()

    def push_file(self, branch: str, file_path: str, content: str, commit_msg: str) -> None:
        self.ensure_branch(branch)
        _, file_sha = self.get_file_content(file_path, ref=branch)
        
        payload = {
            "message": commit_msg,
            "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
            "branch": branch
        }
        if file_sha:
            payload["sha"] = file_sha

        resp = httpx.put(
            f"{self._get_base_url()}/contents/{file_path}",
            headers=self.headers,
            json=payload
        )
        resp.raise_for_status()

    def create_or_update_pr(self, title: str, body: str, branch: str) -> PullRequest:
        # Check if PR exists
        url = f"{self._get_base_url()}/pulls"
        resp = httpx.get(url, params={"head": f"{self.owner}:{branch}", "state": "open"}, headers=self.headers)
        resp.raise_for_status()
        prs = resp.json()
        
        if prs:
            pr = prs[0]
            # Update body if needed
            httpx.patch(pr["url"], headers=self.headers, json={"body": body})
            return PullRequest(title=pr["title"], branch=branch, url=pr["html_url"])
            
        # Create new PR
        resp = httpx.post(
            url,
            headers=self.headers,
            json={
                "title": title,
                "body": body,
                "head": branch,
                "base": self.base_branch
            }
        )
        resp.raise_for_status()
        data = resp.json()
        return PullRequest(title=data["title"], branch=branch, url=data["html_url"])

    def get_pr_comments(self, branch: str) -> list[str]:
        if self.settings.dry_run or not self.settings.github_token:
            return []
            
        # Find PR
        url = f"{self._get_base_url()}/pulls"
        resp = httpx.get(url, params={"head": f"{self.owner}:{branch}", "state": "open"}, headers=self.headers)
        if resp.status_code != 200 or not resp.json():
            return []
        
        pr_number = resp.json()[0]["number"]
        comments_url = f"{self._get_base_url()}/issues/{pr_number}/comments"
        c_resp = httpx.get(comments_url, headers=self.headers)
        if c_resp.status_code != 200:
            return []
            
        return [c["body"] for c in c_resp.json()]
