from __future__ import annotations

import logging

from app.clients.github import GitHubClient
from app.clients.jira import JiraClient
from app.clients.llm import LLMClient
from app.config import Settings
from app.policy import evaluate_memory_policy, memory_recommendation
from app.schemas import AgentDecision, IncidentPayload, IncidentType, PolicyStatus, PullRequest

logger = logging.getLogger(__name__)


def diagnose(incident: IncidentPayload, settings: Settings) -> AgentDecision:
    text = f"{incident.reason}\n{incident.alert_name}\n{incident.logs}\n{incident.describe_snapshot}".lower()
    if "oomkilled" in text or "outofmemory" in text or "out of memory" in text:
        recommendation = memory_recommendation(incident)
        policy_status, policy_reason = evaluate_memory_policy(recommendation, settings.max_memory_limit_gi)
        return AgentDecision(
            incident_type=IncidentType.OOM_KILLED,
            confidence=0.86,
            summary=f"{incident.workload_name} was OOMKilled in namespace {incident.namespace}.",
            evidence=_evidence(incident, ["OOMKilled signal found", "previous logs/describes were included"]),
            recommended_action=(
                f"Open a config PR to raise memory limit from {recommendation.current_limit} "
                f"to {recommendation.proposed_limit}."
                if recommendation
                else "Human review required because current memory limit was not found."
            ),
            pr_required=policy_status == PolicyStatus.ALLOWED,
            policy_status=policy_status,
            policy_reason=policy_reason,
            memory_recommendation=recommendation,
        )

    if "crashloopbackoff" in text or "crash loop" in text:
        return AgentDecision(
            incident_type=IncidentType.CRASH_LOOP,
            confidence=0.78,
            summary=f"{incident.workload_name} is in CrashLoopBackOff in namespace {incident.namespace}.",
            evidence=_evidence(incident, ["CrashLoopBackOff signal found", "exit or event context should be reviewed"]),
            recommended_action="Do not create a PR in V1; attach logs and ask an SRE to inspect startup failure.",
            pr_required=False,
            policy_status=PolicyStatus.NOT_APPLICABLE,
            policy_reason="CrashLoopBackOff is diagnosis-only in V1.",
        )

    return AgentDecision(
        incident_type=IncidentType.UNKNOWN,
        confidence=0.35,
        summary=f"Unsupported Kubernetes alert for {incident.workload_name}.",
        evidence=_evidence(incident, ["No supported V1 incident type matched"]),
        recommended_action="Create a Jira note only and route to human review.",
        pr_required=False,
        policy_status=PolicyStatus.NOT_APPLICABLE,
        policy_reason="Unsupported incident type.",
    )


def handle_incident(payload: dict, settings: Settings, redis_client) -> dict:
    from app.robusta_parser import parse_robusta_payload
    from app.schemas import JiraIssue

    incident = parse_robusta_payload(payload)
    decision = diagnose(incident, settings)
    llm = LLMClient(settings)
    jira = JiraClient(settings)

    decision.llm_diagnosis = llm.generate_diagnosis(incident, decision)
    
    correlation_key = f"active_issue:{incident.namespace}:{incident.workload_name}"
    existing_issue_key = redis_client.get(correlation_key)
    
    pr: PullRequest | None = None
    is_appended = False

    if existing_issue_key:
        issue = JiraIssue(key=existing_issue_key, url=f"{settings.jira_base_url}/browse/{existing_issue_key}")
        comment = render_jira_comment(incident, decision, pr=None)
        comment = f"## 🔄 Subsequent Incident Detected\n\n" + comment
        jira.add_comment(issue, comment)
        redis_client.expire(correlation_key, settings.correlation_ttl_seconds)
        is_appended = True
    else:
        issue = jira.create_issue(incident, decision)
        jira.add_comment(issue, render_jira_comment(incident, decision, pr=None))
        if decision.pr_required:
            logger.info("AI-Remediation requested. Remediation Agent will pick up issue %s via Jira polling.", issue.key)
        redis_client.setex(correlation_key, settings.correlation_ttl_seconds, issue.key)

    logger.info(
        "incident.processed type=%s namespace=%s workload=%s pr_required=%s policy=%s appended=%s",
        decision.incident_type,
        incident.namespace,
        incident.workload_name,
        decision.pr_required,
        decision.policy_status,
        is_appended,
    )
    return {
        "issue": issue.model_dump(),
        "decision": decision.model_dump(mode="json"),
        "pull_request": pr.model_dump() if pr else None,
        "is_appended": is_appended,
    }


def render_jira_comment(incident: IncidentPayload, decision: AgentDecision, pr: PullRequest | None) -> str:
    lines = [
        f"## K8s-Agent V1 Diagnosis: {decision.incident_type}",
        f"- Workload: `{incident.namespace}/{incident.workload_name}`",
        f"- Confidence: `{decision.confidence:.2f}`",
        f"- Summary: {decision.summary}",
        f"- Recommended action: {decision.recommended_action}",
        f"- Policy: `{decision.policy_status}` - {decision.policy_reason}",
    ]
    if decision.llm_diagnosis:
        lines.append(f"\n### LLM Diagnosis\n{decision.llm_diagnosis}\n")
    if pr:
        lines.append(f"- PR: [{pr.title}]({pr.url})")
    if decision.evidence:
        lines.append("### Evidence")
        lines.extend(f"- {item}" for item in decision.evidence)
    return "\n".join(lines)


def _evidence(incident: IncidentPayload, defaults: list[str]) -> list[str]:
    items = list(defaults)
    if incident.logs:
        items.append(f"Log sample: {incident.logs.splitlines()[0][:160]}")
    if incident.events:
        items.append(f"Event sample: {incident.events[0][:160]}")
    return items

