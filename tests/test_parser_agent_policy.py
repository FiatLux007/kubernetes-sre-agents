import json
from pathlib import Path

from app.agent import diagnose
from app.config import Settings
from app.policy import evaluate_memory_policy, memory_recommendation
from app.robusta_parser import fingerprint, parse_robusta_payload
from app.schemas import IncidentType, PolicyStatus


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_oom_fixture_requires_pr():
    incident = parse_robusta_payload(load_fixture("oom_alert.json"))
    decision = diagnose(incident, Settings())

    assert decision.incident_type == IncidentType.OOM_KILLED
    assert decision.pr_required is True
    assert decision.memory_recommendation is not None
    assert decision.memory_recommendation.proposed_limit == "2Gi"


def test_crashloop_fixture_is_diagnosis_only():
    incident = parse_robusta_payload(load_fixture("crashloop_alert.json"))
    decision = diagnose(incident, Settings())

    assert decision.incident_type == IncidentType.CRASH_LOOP
    assert decision.pr_required is False
    assert decision.policy_status == PolicyStatus.NOT_APPLICABLE


def test_fingerprint_ignores_random_pod_suffix():
    payload = load_fixture("oom_alert.json")
    incident_a = parse_robusta_payload(payload)
    payload["labels"]["pod"] = "oom-demo-6d7f8f4c9f-zz999"
    incident_b = parse_robusta_payload(payload)

    assert fingerprint(incident_a) == fingerprint(incident_b)


def test_memory_policy_blocks_above_max():
    payload = load_fixture("oom_alert.json")
    payload["labels"]["memory_limit"] = "3Gi"
    incident = parse_robusta_payload(payload)
    recommendation = memory_recommendation(incident)
    status, reason = evaluate_memory_policy(recommendation, max_gi=4)

    assert status == PolicyStatus.BLOCKED
    assert "exceeds max" in reason

