from __future__ import annotations

import re

from app.schemas import IncidentPayload, MemoryRecommendation, PolicyStatus


def memory_recommendation(incident: IncidentPayload) -> MemoryRecommendation | None:
    current = _current_memory_limit(incident)
    if not current:
        return None
    current_gi = parse_memory_gi(current)
    proposed_gi = current_gi * 2
    return MemoryRecommendation(
        current_limit=current,
        proposed_limit=format_gi(proposed_gi),
        reason="OOMKilled incident: propose a single-step 2x memory limit increase for human review.",
    )


def evaluate_memory_policy(recommendation: MemoryRecommendation | None, max_gi: float) -> tuple[PolicyStatus, str]:
    if recommendation is None:
        return PolicyStatus.BLOCKED, "No current memory limit was found; refusing to propose a blind change."
    proposed_gi = parse_memory_gi(recommendation.proposed_limit)
    current_gi = parse_memory_gi(recommendation.current_limit)
    if proposed_gi > current_gi * 2:
        return PolicyStatus.BLOCKED, "Proposed limit exceeds the 2x single-change cap."
    if proposed_gi > max_gi:
        return PolicyStatus.BLOCKED, f"Proposed limit {recommendation.proposed_limit} exceeds max {format_gi(max_gi)}."
    return PolicyStatus.ALLOWED, "Memory recommendation is within V1 policy."


def parse_memory_gi(value: str) -> float:
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([KMGTP]i?|)\s*", value)
    if not match:
        raise ValueError(f"Unsupported memory quantity: {value}")
    number = float(match.group(1))
    unit = match.group(2).lower()
    multipliers = {
        "": 1 / (1024**3),
        "ki": 1 / (1024**2),
        "k": 1000 / (1024**3),
        "mi": 1 / 1024,
        "m": 1000**2 / 1024**3,
        "gi": 1,
        "g": 1000**3 / 1024**3,
        "ti": 1024,
        "t": 1000**4 / 1024**3,
    }
    return number * multipliers[unit]


def format_gi(value: float) -> str:
    number = float(value)
    if number.is_integer():
        return f"{int(number)}Gi"
    return f"{number:.2f}Gi"


def _current_memory_limit(incident: IncidentPayload) -> str:
    resource_limit = (
        incident.resources.get("limits", {}).get("memory")
        if isinstance(incident.resources.get("limits"), dict)
        else None
    )
    if resource_limit:
        return str(resource_limit)
    for mapping in (incident.labels, incident.annotations):
        for key in ("memory_limit", "memory-limit", "resources.limits.memory"):
            if key in mapping:
                return mapping[key]
    return ""
