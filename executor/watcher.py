"""
Pod Status Watcher — Option 1: poll K8s pod/container status mỗi CDO_POLL_INTERVAL_S giây.

Không cần Events API — chỉ dùng `pods: get/list` đã có trong executor-rbac.yaml.

Signal sources:
  - containerStatus.state.waiting.reason     → OOMKilled, CrashLoopBackOff, ImagePullBackOff
  - containerStatus.lastState.terminated.exitCode == 137  → OOM_KILL
  - containerStatus.restartCount > threshold → CRASH_LOOP

Output: list[FaultEvent] mỗi pod bất thường, mỗi event chứa telemetry_window
đúng format contract-new-4 để gọi thẳng vào /v1/detect.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from config import CONFIG

_WAITING_REASON_MAP: dict[str, str] = {
    "OOMKilled":        "OOM_KILL",
    "CrashLoopBackOff": "CRASH_LOOP",
    "Error":            "CRASH_LOOP",
    "ImagePullBackOff": "BAD_DEPLOY",
    "ErrImagePull":     "BAD_DEPLOY",
}
_OOM_EXIT_CODE = 137


@dataclass
class FaultEvent:
    namespace: str
    service: str
    deployment: str
    suspected_fault_type: str
    telemetry_window: list[dict] = field(default_factory=list)


def collect_fault_events(k8s, namespaces: tuple[str, ...], cfg=CONFIG) -> list[FaultEvent]:
    """
    Poll pod status trong tất cả tenant namespace.
    Trả [] nếu k8s mock mode (không có cluster thật).
    """
    events: list[FaultEvent] = []
    for ns in namespaces:
        pod_list = k8s.list_pods_raw(ns)
        if pod_list is None:
            continue
        for pod in pod_list.items:
            if not pod.status or not pod.status.container_statuses:
                continue
            ev = _inspect_pod(pod, ns, cfg)
            if ev is not None:
                events.append(ev)
    return events


def _inspect_pod(pod, namespace: str, cfg) -> FaultEvent | None:
    deployment = _infer_deployment(pod)
    service = (pod.metadata.labels or {}).get("app", deployment)
    signals: list[dict] = []
    fault_type: str | None = None

    for cs in pod.status.container_statuses:
        # 1. waiting reason (CrashLoopBackOff, OOMKilled, ...)
        if cs.state and cs.state.waiting:
            reason = cs.state.waiting.reason or ""
            ft = _WAITING_REASON_MAP.get(reason)
            if ft:
                fault_type = fault_type or ft
                signals.append(_signal(service, namespace, deployment,
                                       "pod_waiting_reason", reason, cfg.tenant_id))

        # 2. exit code 137 từ last terminated state → OOM ngay cả khi pod đã restart xong
        if cs.last_state and cs.last_state.terminated:
            if cs.last_state.terminated.exit_code == _OOM_EXIT_CODE:
                fault_type = fault_type or "OOM_KILL"
                signals.append(_signal(service, namespace, deployment,
                                       "exit_code_oom", _OOM_EXIT_CODE, cfg.tenant_id))

        # 3. restart count vượt ngưỡng → CRASH_LOOP ngay cả khi pod đang Running
        if (cs.restart_count or 0) > cfg.restart_count_threshold:
            fault_type = fault_type or "CRASH_LOOP"
            signals.append(_signal(service, namespace, deployment,
                                   "restart_count", cs.restart_count, cfg.tenant_id))

    if not fault_type or not signals:
        return None
    return FaultEvent(namespace=namespace, service=service, deployment=deployment,
                      suspected_fault_type=fault_type, telemetry_window=signals)


def scrape_deployment_telemetry(k8s, namespace: str, deployment: str,
                                cfg=CONFIG) -> list[dict]:
    """
    Scrape telemetry hiện tại của 1 deployment cho /v1/verify post-action window.
    Khác collect_fault_events: báo cáo CẢ trạng thái healthy (để AI xác nhận đã hồi phục),
    không chỉ pod lỗi. Trả [] nếu mock mode (caller fallback về window gốc).
    """
    pod_list = k8s.list_pods_raw(namespace)
    if pod_list is None:
        return []
    signals: list[dict] = []
    for pod in pod_list.items:
        if _infer_deployment(pod) != deployment:
            continue
        service = (pod.metadata.labels or {}).get("app", deployment)
        phase = pod.status.phase if pod.status else "Unknown"
        signals.append(_signal(service, namespace, deployment,
                               "pod_phase", phase, cfg.tenant_id))
        for cs in (pod.status.container_statuses or []):
            signals.append(_signal(service, namespace, deployment,
                                   "container_ready", bool(cs.ready), cfg.tenant_id))
            signals.append(_signal(service, namespace, deployment,
                                   "restart_count", cs.restart_count or 0, cfg.tenant_id))
            if cs.state and cs.state.waiting and cs.state.waiting.reason:
                signals.append(_signal(service, namespace, deployment,
                                       "pod_waiting_reason", cs.state.waiting.reason,
                                       cfg.tenant_id))
    return signals


def _signal(service: str, namespace: str, deployment: str,
            signal_name: str, value, tenant_id: str) -> dict:
    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "tenant_id": tenant_id,
        "service": service,
        "signal_name": signal_name,
        "value": value,
        "labels": {
            "system": "K8S_NATIVE",
            "namespace": namespace,
            "deployment": deployment,
        },
    }


def _infer_deployment(pod) -> str:
    """Suy ra deployment name từ ownerReference ReplicaSet → strip hash suffix."""
    for ref in (pod.metadata.owner_references or []):
        if ref.kind == "ReplicaSet":
            parts = ref.name.rsplit("-", 1)
            return parts[0] if len(parts) == 2 else ref.name
    return pod.metadata.name
