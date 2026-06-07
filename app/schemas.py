from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class IncidentType(StrEnum):
    OOM_KILLED = "OOMKilled"
    CRASH_LOOP = "CrashLoopBackOff"
    UNKNOWN = "Unknown"


class PolicyStatus(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


class IncidentPayload(BaseModel):
    cluster: str = "minikube"
    namespace: str
    workload_kind: str = "Deployment"
    workload_name: str
    pod_name: str = ""
    container_name: str = ""
    alert_name: str = ""
    reason: str
    severity: str = "warning"
    logs: str = ""
    describe_snapshot: str = ""
    events: list[str] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    resources: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DedupeResult(BaseModel):
    key: str
    is_new: bool
    count: int


class MemoryRecommendation(BaseModel):
    current_limit: str
    proposed_limit: str
    reason: str


class AgentDecision(BaseModel):
    incident_type: IncidentType
    confidence: float
    summary: str
    evidence: list[str] = Field(default_factory=list)
    recommended_action: str
    pr_required: bool
    policy_status: PolicyStatus
    policy_reason: str = ""
    llm_diagnosis: str = ""
    memory_recommendation: MemoryRecommendation | None = None


class JiraIssue(BaseModel):
    key: str
    url: str


class PullRequest(BaseModel):
    title: str
    url: str
    branch: str

