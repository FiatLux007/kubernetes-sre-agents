from __future__ import annotations

import re
from typing import Any

from app.schemas import IncidentPayload


def parse_robusta_payload(payload: dict[str, Any]) -> IncidentPayload:
    # Handle Robusta native Finding format
    subject = payload.get("subject", {})
    service = payload.get("service", {})

    labels = _collect_mapping(payload, ["labels", "commonLabels"])
    alert = _first_mapping(payload, ["alert", "alerts", "finding", "issue", "data"])
    labels.update(_collect_mapping(alert, ["labels", "commonLabels"]))
    labels.update(subject.get("labels") or {})
    
    annotations = _collect_mapping(payload, ["annotations", "commonAnnotations"])
    annotations.update(_collect_mapping(alert, ["annotations", "commonAnnotations"]))
    annotations.update(subject.get("annotations") or {})

    text = _all_text(payload)
    reason = _first_string(
        payload,
        alert,
        keys=["aggregation_key", "reason", "alert_name", "alertName", "name", "title", "status"],
        default=_infer_reason(text),
    )
    alert_name = _first_string(
        payload,
        alert,
        keys=["title", "alert_name", "alertName", "alertname", "name"],
        default=reason,
    )

    namespace = _value(labels, "namespace", "kubernetes_namespace", "k8s_namespace") or _first_string(
        payload, alert, subject, service, keys=["namespace"], default=""
    )
    workload_name = (
        _value(labels, "workload", "workload_name", "deployment", "app", "app.kubernetes.io/name")
        or _first_string(payload, alert, service, keys=["workload_name", "deployment", "name"], default="")
    )
    
    pod_name = ""
    if subject.get("kind") == "pod":
        pod_name = subject.get("name", "")
    if not pod_name:
        pod_name = _value(labels, "pod", "pod_name", "pod_name") or _first_string(
            payload, alert, keys=["pod", "pod_name"], default=""
        )

    container_name = subject.get("container") or _value(labels, "container", "container_name") or _first_string(
        payload, alert, keys=["container", "container_name"], default=""
    )

    if not workload_name and pod_name:
        workload_name = _workload_from_pod(pod_name)

    logs = _extract_text_block(payload, ["logs", "log", "previous_logs", "previousLogs"])
    describe_snapshot = _extract_text_block(payload, ["describe", "describe_snapshot", "snapshot"])
    events = _extract_events(payload)

    if not namespace:
        namespace = "default"
    if not workload_name:
        workload_name = "unknown-workload"

    return IncidentPayload(
        cluster=_first_string(payload, alert, keys=["cluster_name", "cluster"], default="minikube"),
        namespace=namespace,
        workload_kind=service.get("resource_type") or _first_string(payload, alert, keys=["workload_kind", "kind"], default="Deployment"),
        workload_name=workload_name,
        pod_name=pod_name,
        container_name=container_name,
        alert_name=alert_name,
        reason=reason,
        severity=_first_string(payload, alert, keys=["severity"], default="warning"),
        logs=logs,
        describe_snapshot=describe_snapshot,
        events=events,
        labels={str(k): str(v) for k, v in labels.items()},
        annotations={str(k): str(v) for k, v in annotations.items()},
        resources=payload.get("resources") if isinstance(payload.get("resources"), dict) else {},
        raw=payload,
    )


def error_signature(incident: IncidentPayload) -> str:
    text = f"{incident.reason}\n{incident.alert_name}\n{incident.logs}\n{incident.describe_snapshot}".lower()
    if "java.lang.outofmemoryerror" in text:
        return "java_out_of_memory_error"
    if "oomkilled" in text or "out of memory" in text:
        return "oom"
    if "crashloopbackoff" in text:
        return "crashloopbackoff"
    match = re.search(r"(error|exception|failed)[^\n]{0,80}", text)
    if match:
        return _slug(match.group(0))[:80]
    return _slug(incident.reason or incident.alert_name or "unknown")


def fingerprint(incident: IncidentPayload) -> str:
    parts = [
        "incident",
        incident.cluster,
        incident.namespace,
        incident.workload_kind,
        incident.workload_name,
        incident.container_name or "container",
        incident.alert_name or "alert",
        incident.reason or "reason",
        error_signature(incident),
    ]
    return ":".join(_slug(part) for part in parts)


def _first_mapping(payload: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value[0]
    return {}


def _collect_mapping(payload: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            return dict(value)
    return {}


def _first_string(*objects: dict[str, Any], keys: list[str], default: str) -> str:
    for obj in objects:
        for key in keys:
            value = obj.get(key)
            if value is not None and not isinstance(value, (dict, list)):
                return str(value)
    return default


def _value(mapping: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return str(mapping[key])
    return ""


def _extract_text_block(payload: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "\n".join(str(item) for item in value)
    return ""


def _extract_events(payload: dict[str, Any]) -> list[str]:
    value = payload.get("events", [])
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value]
    return []


def _all_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_all_text(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_all_text(v) for v in value)
    return str(value)


def _infer_reason(text: str) -> str:
    lower = text.lower()
    if "oomkilled" in lower or "outofmemory" in lower or "out of memory" in lower:
        return "OOMKilled"
    if "crashloopbackoff" in lower:
        return "CrashLoopBackOff"
    return "KubernetesAlert"


def _workload_from_pod(pod_name: str) -> str:
    return re.sub(r"-[a-f0-9]{8,10}-[a-z0-9]{5}$", "", pod_name)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value).strip().lower()).strip("-")
    return slug or "unknown"

