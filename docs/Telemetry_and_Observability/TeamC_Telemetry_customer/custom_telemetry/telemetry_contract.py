"""Contract-first telemetry helpers for Team C.

The executor accepts a plain telemetry_window list. This module makes mock
scenario data and real collector data converge to the frozen telemetry contract
before Team C sends it to AI /v1/detect or stores evidence.
"""
from __future__ import annotations

import copy
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any


TENANT_ID = "6c8b4b2b-4d45-4209-a1b4-4b532d56a31c"
DEFAULT_SYSTEM = "E-COMMERCE"

CONTRACT_SIGNALS = {
    "service_error_rate",
    "service_latency_p95",
    "container_resource_usage",
    "application_log_event",
    "distributed_trace_error_event",
    "pod_oom_event",
    "service_unhealthy",
    "queue_backlog",
    "service_throughput_rps",
    "container_restart_count",
    "secret_expiry_warning",
    "db_connection_pool_saturation",
}

CONTRACT_TOP_LEVEL_FIELDS = {"ts", "tenant_id", "service", "signal_name", "value", "labels"}

_INTERNAL_SIGNAL_MAP = {
    ("pod_waiting_reason", "OOMKilled"): ("pod_oom_event", "OOMKilled"),
    ("pod_waiting_reason", "CrashLoopBackOff"): ("service_unhealthy", "CrashLoopBackOff"),
    ("pod_waiting_reason", "ImagePullBackOff"): ("service_unhealthy", "ImagePullBackOff"),
    ("pod_waiting_reason", "ErrImagePull"): ("service_unhealthy", "ErrImagePull"),
    ("pod_waiting_reason", "Error"): ("service_unhealthy", "Container waiting Error"),
    ("exit_code_oom", None): ("pod_oom_event", "exit_code_137"),
    ("restart_count", None): ("container_restart_count", None),
    ("pod_phase", "Running"): ("service_unhealthy", "pod_phase_running"),
    ("pod_phase", "Pending"): ("service_unhealthy", "pod_phase_pending"),
    ("pod_phase", "Failed"): ("service_unhealthy", "pod_phase_failed"),
    ("container_ready", False): ("service_unhealthy", "container_not_ready"),
    ("container_ready", True): ("service_unhealthy", "container_ready"),
    ("readiness_fail_after_deploy", None): ("service_unhealthy", "readiness_fail_after_deploy"),
    ("container_memory_pct", None): ("container_resource_usage", None),
    ("hpa_at_max_replicas", None): ("service_unhealthy", "hpa_at_max_replicas"),
    ("minor_blip", None): ("service_unhealthy", "minor_blip"),
}

_SECRET_PATTERNS = [
    (re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*[^&\s]+"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)(token|api[_-]?key|secret)\s*[:=]\s*[A-Za-z0-9._~+/=-]{8,}"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)(authorization:\s*bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1[REDACTED]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL_REDACTED]"),
    (re.compile(r"(?i)(postgres|mysql|mongodb)://[^\s]+"), "[CONNECTION_STRING_REDACTED]"),
]


class TelemetryContractError(ValueError):
    """Raised when a telemetry point cannot be made contract-compliant."""


def utc_now_ms() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def epoch_to_rfc3339_ms(epoch_seconds: float | int | str) -> str:
    return datetime.fromtimestamp(float(epoch_seconds), timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def scrub_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    scrubbed = value
    for pattern, repl in _SECRET_PATTERNS:
        scrubbed = pattern.sub(repl, scrubbed)
    return scrubbed


def normalize_point(point: dict[str, Any], source_mode: str) -> dict[str, Any]:
    """Return one telemetry point that satisfies the telemetry contract."""
    p = copy.deepcopy(point)
    labels = dict(p.get("labels") or {})
    original_signal = p.get("signal_name")
    raw_value = p.get("value")

    signal_name, value = _normalize_signal(original_signal, raw_value)
    labels.setdefault("system", p.get("system") or DEFAULT_SYSTEM)
    labels["cdo_source_mode"] = source_mode
    labels["cdo_original_signal"] = original_signal

    out = {
        "ts": _normalize_timestamp(p.get("ts")),
        "tenant_id": p.get("tenant_id") or TENANT_ID,
        "service": p.get("service") or labels.get("service") or labels.get("deployment"),
        "signal_name": signal_name,
        "value": scrub_value(value),
        "labels": labels,
    }
    validate_point(out)
    return out


def normalize_window(points: list[dict[str, Any]], source_mode: str) -> list[dict[str, Any]]:
    return [normalize_point(point, source_mode) for point in points]


def validate_window(points: list[dict[str, Any]]) -> None:
    for index, point in enumerate(points):
        try:
            validate_point(point)
        except TelemetryContractError as exc:
            raise TelemetryContractError(f"telemetry_window[{index}]: {exc}") from exc


def auto_normalize(raw: Any) -> list[dict[str, Any]]:
    """Detect common raw telemetry shapes and return contract telemetry points."""
    if isinstance(raw, dict) and "telemetry_window" in raw:
        return normalize_window(raw["telemetry_window"], "mock_scenario")
    if isinstance(raw, dict) and raw.get("status") == "success" and "result" in raw.get("data", {}):
        return _auto_prometheus(raw)
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        return from_kubernetes_events(raw)
    if isinstance(raw, dict) and "resourceSpans" in raw:
        return from_otel_export(raw)
    if isinstance(raw, dict) and _looks_like_log(raw):
        return from_log_events([raw])
    if isinstance(raw, dict) and "logEvents" in raw:
        return from_log_events(raw["logEvents"], raw)
    if isinstance(raw, list):
        if not raw:
            return []
        if all(isinstance(item, dict) and _looks_like_log(item) for item in raw):
            return from_log_events(raw)
        if all(isinstance(item, dict) and _looks_like_span(item) for item in raw):
            return from_otel_spans(raw)
        if all(isinstance(item, dict) and "signal_name" in item for item in raw):
            return normalize_window(raw, "contract_or_internal_window")
    raise TelemetryContractError("unsupported raw telemetry shape for auto mode")


def validate_point(point: dict[str, Any]) -> None:
    required = ("ts", "tenant_id", "service", "signal_name", "value")
    missing = [key for key in required if key not in point or point[key] in (None, "")]
    if missing:
        raise TelemetryContractError(f"missing required fields: {', '.join(missing)}")
    extra = sorted(set(point) - CONTRACT_TOP_LEVEL_FIELDS)
    if extra:
        raise TelemetryContractError(f"unsupported top-level fields: {', '.join(extra)}")

    normalized_ts = _normalize_timestamp(point["ts"])
    if point["ts"] != normalized_ts:
        raise TelemetryContractError("ts must be RFC3339 UTC with millisecond precision")
    try:
        parsed = uuid.UUID(str(point["tenant_id"]))
    except ValueError as exc:
        raise TelemetryContractError("tenant_id must be a UUID") from exc
    if parsed.version != 4:
        raise TelemetryContractError("tenant_id must be UUID v4")

    if point["signal_name"] not in CONTRACT_SIGNALS:
        raise TelemetryContractError(f"unsupported signal_name: {point['signal_name']}")
    if not isinstance(point.get("labels"), dict):
        raise TelemetryContractError("labels must be an object")
    if not point["labels"].get("system"):
        raise TelemetryContractError("labels.system is required")
    if not isinstance(point["value"], (int, float, str)):
        raise TelemetryContractError("value must be number or string")


def from_prometheus_result(
    prometheus_response: dict[str, Any],
    signal_name: str,
    service: str,
    namespace: str,
    deployment: str,
    source_mode: str = "real_prometheus",
) -> list[dict[str, Any]]:
    """Convert Prometheus HTTP API query output into contract telemetry."""
    result = prometheus_response.get("data", {}).get("result", [])
    points: list[dict[str, Any]] = []
    for item in result:
        metric = item.get("metric", {})
        raw_value = item.get("value") or item.get("values", [[time.time(), 0]])[-1]
        ts, value = raw_value[0], raw_value[1]
        labels = {
            "system": metric.get("system", DEFAULT_SYSTEM),
            "namespace": metric.get("namespace", namespace),
            "deployment": metric.get("deployment", deployment),
            "pod_name": metric.get("pod"),
            "container": metric.get("container"),
            "endpoint": metric.get("endpoint") or metric.get("path"),
        }
        points.append(
            normalize_point(
                {
                    "ts": epoch_to_rfc3339_ms(ts),
                    "tenant_id": TENANT_ID,
                    "service": metric.get("service") or metric.get("app") or service,
                    "signal_name": signal_name,
                    "value": _number_or_string(value),
                    "labels": {k: v for k, v in labels.items() if v},
                },
                source_mode,
            )
        )
    return points


def from_kubernetes_events(events_json: dict[str, Any], source_mode: str = "real_k8s_event") -> list[dict[str, Any]]:
    """Convert `kubectl get events -A -o json` output into contract telemetry."""
    points: list[dict[str, Any]] = []
    for item in events_json.get("items", []):
        involved = item.get("involvedObject", {})
        namespace = item.get("metadata", {}).get("namespace") or involved.get("namespace")
        reason = item.get("reason") or ""
        message = item.get("message") or reason
        deployment = _deployment_from_event(involved.get("name") or "unknown")
        service = item.get("metadata", {}).get("labels", {}).get("app") or deployment
        if reason == "OOMKilling" or "OOMKilled" in message:
            signal_name = "pod_oom_event"
        elif reason in {"Unhealthy", "BackOff", "Failed", "FailedScheduling"}:
            signal_name = "service_unhealthy"
        else:
            continue
        points.append(
            normalize_point(
                {
                    "ts": item.get("eventTime") or item.get("lastTimestamp") or item.get("firstTimestamp"),
                    "tenant_id": TENANT_ID,
                    "service": service,
                    "signal_name": signal_name,
                    "value": message,
                    "labels": {
                        "system": "K8S_NATIVE",
                        "namespace": namespace,
                        "deployment": deployment,
                        "pod_name": involved.get("name"),
                    },
                },
                source_mode,
            )
        )
    return points


def from_log_events(log_events: list[dict[str, Any]], parent: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Convert raw log records, Fluent Bit-like records, or CloudWatch logEvents."""
    parent = parent or {}
    points: list[dict[str, Any]] = []
    for event in log_events:
        message = (
            event.get("message")
            or event.get("log")
            or event.get("msg")
            or event.get("@message")
            or event.get("value")
        )
        if message is None:
            continue
        labels = _base_labels(event, parent)
        level = event.get("level") or event.get("severity") or event.get("log_level")
        if level:
            labels["level"] = str(level).upper()
        points.append(
            normalize_point(
                {
                    "ts": _timestamp_from_raw(
                        event.get("ts")
                        or event.get("timestamp")
                        or event.get("@timestamp")
                        or event.get("time")
                    ),
                    "tenant_id": event.get("tenant_id") or parent.get("tenant_id") or TENANT_ID,
                    "service": _first(event, parent, "service", "service_name", "app", "deployment") or "unknown-service",
                    "signal_name": "application_log_event",
                    "value": message,
                    "labels": labels,
                },
                "real_log_event",
            )
        )
    return points


def from_otel_spans(spans: list[dict[str, Any]], parent: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Convert simplified OpenTelemetry span dictionaries into trace telemetry."""
    parent = parent or {}
    points: list[dict[str, Any]] = []
    for span in spans:
        status = span.get("status") or {}
        status_code = status.get("code") if isinstance(status, dict) else status
        if str(status_code).upper() not in {"ERROR", "STATUS_CODE_ERROR", "2"}:
            continue
        labels = _base_labels(span, parent)
        labels.update(
            {
                "trace_id": span.get("traceId") or span.get("trace_id"),
                "span_id": span.get("spanId") or span.get("span_id"),
                "operation": span.get("name") or span.get("operation"),
            }
        )
        points.append(
            normalize_point(
                {
                    "ts": _timestamp_from_raw(
                        span.get("ts")
                        or span.get("startTimeUnixNano")
                        or span.get("start_time_unix_nano")
                        or span.get("startTime")
                    ),
                    "tenant_id": span.get("tenant_id") or parent.get("tenant_id") or TENANT_ID,
                    "service": _first(span, parent, "service", "serviceName", "service_name", "app") or "unknown-service",
                    "signal_name": "distributed_trace_error_event",
                    "value": span.get("status", {}).get("message", "ERROR") if isinstance(span.get("status"), dict) else "ERROR",
                    "labels": {k: v for k, v in labels.items() if v},
                },
                "real_otel_span",
            )
        )
    return points


def from_otel_export(otel_export: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a minimal OTLP JSON export with resourceSpans/scopeSpans/spans."""
    points: list[dict[str, Any]] = []
    for resource_span in otel_export.get("resourceSpans", []):
        resource_attrs = _attributes_to_dict(resource_span.get("resource", {}).get("attributes", []))
        parent = {
            "service": resource_attrs.get("service.name"),
            "namespace": resource_attrs.get("k8s.namespace.name"),
            "deployment": resource_attrs.get("k8s.deployment.name"),
            "pod_name": resource_attrs.get("k8s.pod.name"),
            "system": resource_attrs.get("system") or DEFAULT_SYSTEM,
        }
        for scope_span in resource_span.get("scopeSpans", []):
            points.extend(from_otel_spans(scope_span.get("spans", []), parent))
    return points


def _normalize_signal(signal_name: str, value: Any) -> tuple[str, Any]:
    if signal_name in CONTRACT_SIGNALS:
        return signal_name, value
    mapped = _INTERNAL_SIGNAL_MAP.get((signal_name, value)) or _INTERNAL_SIGNAL_MAP.get((signal_name, None))
    if mapped:
        mapped_signal, mapped_value = mapped
        return mapped_signal, value if mapped_value is None else mapped_value
    raise TelemetryContractError(f"cannot map internal signal to contract enum: {signal_name}")


def _auto_prometheus(raw: dict[str, Any]) -> list[dict[str, Any]]:
    result = raw.get("data", {}).get("result", [])
    metric = result[0].get("metric", {}) if result else {}
    signal_name = raw.get("signal_name") or metric.get("signal_name") or _infer_signal_from_metric(metric)
    service = raw.get("service") or metric.get("service") or metric.get("app") or metric.get("deployment") or "unknown-service"
    namespace = raw.get("namespace") or metric.get("namespace") or "unknown"
    deployment = raw.get("deployment") or metric.get("deployment") or service
    return from_prometheus_result(raw, signal_name, service, namespace, deployment)


def _infer_signal_from_metric(metric: dict[str, Any]) -> str:
    name = metric.get("__name__", "")
    if "latency" in name or "duration" in name:
        return "service_latency_p95"
    if "error" in name or "5xx" in name:
        return "service_error_rate"
    if "restart" in name:
        return "container_restart_count"
    if "memory" in name or "container" in name:
        return "container_resource_usage"
    if "queue" in name or "backlog" in name:
        return "queue_backlog"
    return "service_unhealthy"


def _looks_like_log(item: dict[str, Any]) -> bool:
    return any(key in item for key in ("message", "log", "msg", "@message", "log_level", "severity"))


def _looks_like_span(item: dict[str, Any]) -> bool:
    return any(key in item for key in ("traceId", "trace_id")) and any(key in item for key in ("spanId", "span_id", "name"))


def _base_labels(item: dict[str, Any], parent: dict[str, Any]) -> dict[str, Any]:
    labels = dict(parent.get("labels") or {})
    labels.update(dict(item.get("labels") or {}))
    for src, dst in (
        ("system", "system"),
        ("namespace", "namespace"),
        ("k8s_namespace", "namespace"),
        ("deployment", "deployment"),
        ("k8s_deployment", "deployment"),
        ("pod", "pod_name"),
        ("pod_name", "pod_name"),
        ("container", "container"),
        ("endpoint", "endpoint"),
    ):
        labels.setdefault(dst, item.get(src) or parent.get(src))
    labels.setdefault("system", DEFAULT_SYSTEM)
    return {k: v for k, v in labels.items() if v}


def _first(item: dict[str, Any], parent: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if item.get(key):
            return item[key]
        if parent.get(key):
            return parent[key]
    return None


def _timestamp_from_raw(value: Any) -> str:
    if value is None:
        return utc_now_ms()
    if isinstance(value, (int, float)):
        # CloudWatch uses milliseconds; OTLP may use nanoseconds.
        if value > 10_000_000_000_000_000:
            return epoch_to_rfc3339_ms(value / 1_000_000_000)
        if value > 10_000_000_000:
            return epoch_to_rfc3339_ms(value / 1000)
        return epoch_to_rfc3339_ms(value)
    return _normalize_timestamp(value)


def _attributes_to_dict(attrs: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for attr in attrs:
        key = attr.get("key")
        value = attr.get("value")
        if not key or not isinstance(value, dict):
            continue
        for typed_value in ("stringValue", "intValue", "doubleValue", "boolValue"):
            if typed_value in value:
                out[key] = value[typed_value]
                break
    return out


def _normalize_timestamp(value: Any) -> str:
    if not value:
        return utc_now_ms()
    s = str(value)
    if s.endswith("Z"):
        s_for_parse = s[:-1] + "+00:00"
    else:
        s_for_parse = s
    try:
        parsed = datetime.fromisoformat(s_for_parse)
    except ValueError as exc:
        raise TelemetryContractError(f"ts must be RFC3339 date-time: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _number_or_string(value: Any) -> float | str:
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def _deployment_from_event(name: str) -> str:
    parts = name.rsplit("-", 2)
    if len(parts) == 3:
        return parts[0]
    return name
