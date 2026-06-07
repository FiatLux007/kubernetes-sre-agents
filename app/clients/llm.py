import logging
import json
from typing import Any

import httpx

from app.config import Settings
from app.schemas import AgentDecision, IncidentPayload

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def plan_remediation(
        self,
        original_yaml: str,
        human_comments: list[str],
        *,
        issue_key: str,
        workload_name: str,
    ) -> dict[str, Any]:
        if self.settings.dry_run or not self.settings.llm_api_key:
            return {
                "intent": "update_manifest",
                "summary": f"Dry-run remediation plan for {workload_name}.",
                "changes": [],
                "needs_kubectl_context": False,
                "kubectl_queries": [],
                "risk_level": "low",
            }

        headers = self._anthropic_headers()
        comments_text = "\n".join(f"- {c}" for c in human_comments)
        prompt = (
            "You are planning a Kubernetes GitOps remediation. Return ONLY valid JSON.\n\n"
            f"Issue: {issue_key}\n"
            f"Workload: {workload_name}\n\n"
            f"Human feedback:\n{comments_text}\n\n"
            f"Original YAML:\n```yaml\n{original_yaml}\n```\n\n"
            "JSON schema:\n"
            "{\n"
            '  "intent": "short machine-readable intent",\n'
            '  "summary": "one sentence human summary",\n'
            '  "changes": [{"target": "...", "field": "...", "from": "...", "to": "...", "reason": "..."}],\n'
            '  "needs_kubectl_context": false,\n'
            '  "kubectl_queries": [{"operation": "get|describe|logs", "kind": "deployment|pod", "namespace": "", "name": ""}],\n'
            '  "risk_level": "low|medium|high"\n'
            "}\n"
        )
        payload = {
            "model": self.settings.llm_model,
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}],
        }
        try:
            response = httpx.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers, timeout=30.0)
            response.raise_for_status()
            content = response.json()["content"][0]["text"].strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            plan = json.loads(content.strip())
            return plan if isinstance(plan, dict) else {}
        except Exception as e:
            logger.error("Failed to plan remediation: %s", e)
            return {
                "intent": "update_manifest",
                "summary": f"Fallback remediation plan for {workload_name}.",
                "changes": [],
                "needs_kubectl_context": False,
                "kubectl_queries": [],
                "risk_level": "medium",
            }

    def generate_diagnosis(self, incident: IncidentPayload, decision: AgentDecision) -> str:
        if self.settings.dry_run or not self.settings.llm_api_key:
            logger.info("dry_run.llm diagnosis incident=%s/%s", incident.namespace, incident.workload_name)
            return decision.summary

        headers = self._anthropic_headers()
        
        prompt = f"Analyze this Kubernetes incident and provide a concise 1-paragraph summary:\nAlert: {incident.alert_name}\nReason: {incident.reason}\nLogs: {incident.logs}\nDescribe: {incident.describe_snapshot}"
        
        payload = {
            "model": self.settings.llm_model,
            "max_tokens": 1024,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
        try:
            response = httpx.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"]
        except httpx.HTTPError as e:
            logger.error("Failed to generate LLM diagnosis: %s", e)
            return decision.summary

    def rewrite_yaml(
        self,
        original_yaml: str,
        human_comments: list[str],
        *,
        remediation_plan: dict[str, Any] | None = None,
        k8s_context: dict[str, Any] | None = None,
        validation_errors: list[str] | None = None,
    ) -> str:
        if self.settings.dry_run or not self.settings.llm_api_key:
            return original_yaml
            
        headers = self._anthropic_headers()
        
        comments_text = "\n".join(f"- {c}" for c in human_comments)
        plan_text = json.dumps(remediation_plan or {}, indent=2)
        k8s_context_text = json.dumps(k8s_context or {}, indent=2)
        validation_text = "\n".join(f"- {e}" for e in validation_errors or []) or "- none"
        prompt = (
            f"You are an expert Kubernetes engineer. Please update the following YAML manifest based on the human feedback provided.\n\n"
            f"Human Feedback:\n{comments_text}\n\n"
            f"Structured Remediation Plan:\n{plan_text}\n\n"
            f"Read-only Kubernetes Context:\n{k8s_context_text}\n\n"
            f"Validation errors from prior attempts:\n{validation_text}\n\n"
            f"Original YAML:\n```yaml\n{original_yaml}\n```\n\n"
            f"Output ONLY the complete updated YAML content without any markdown blocks or explanations. Do not include ```yaml or ```."
        )
        
        payload = {
            "model": self.settings.llm_model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}]
        }
        try:
            resp = httpx.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers, timeout=60.0)
            resp.raise_for_status()
            content = resp.json()["content"][0]["text"].strip()
            # Remove markdown if the model hallucinates it
            if content.startswith("```yaml"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            return content.strip()
        except Exception as e:
            logger.error("Failed to rewrite YAML: %s", e)
            return original_yaml

    def _anthropic_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.settings.llm_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
