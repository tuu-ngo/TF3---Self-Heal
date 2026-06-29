"""
Pod Status Watcher — Option 1: poll K8s pod/container status mỗi CDO_POLL_INTERVAL_S giây.

Không cần Events API — chỉ dùng `pods: get/list` đã có trong executor-rbac.yaml.

Signal sources (raw K8s) → ÁNH XẠ về enum signal_name của telemetry-contract §3:
  - state.waiting.reason = OOMKilled                       → pod_oom_event
  - state.waiting.reason = CrashLoopBackOff / Error        → container_restart_count
  - state.waiting.reason = ImagePullBackOff / ErrImagePull → service_unhealthy
  - lastState.terminated.exitCode == 137                   → pod_oom_event
  - restartCount > threshold                               → container_restart_count

⚠ AI Engine validate telemetry theo JSON Schema nghiêm ngặt (enum signal_name +
additionalProperties:false). Mọi signal_name phát đi BẮT BUỘC thuộc 12 giá trị enum,
nếu không sẽ bị reject 400. Vì vậy watcher KHÔNG phát signal_name K8s-native thô.

Output: list[FaultEvent] mỗi pod bất thường, mỗi event chứa telemetry_window
đúng format contract-new-4 để gọi thẳng vào /v1/detect.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from config import CONFIG

# K8s waiting reason → (contract signal_name thuộc enum §3, fault_type nội bộ)
_WAITING_REASON_MAP: dict[str, tuple[str, str]] = {
    "OOMKilled":        ("pod_oom_event", "OOM_KILL"),
    "CrashLoopBackOff": ("container_restart_count", "CRASH_LOOP"),
    "Error":            ("container_restart_count", "CRASH_LOOP"),
    "ImagePullBackOff": ("service_unhealthy", "BAD_DEPLOY"),
    "ErrImagePull":     ("service_unhealthy", "BAD_DEPLOY"),
}
_OOM_EXIT_CODE = 137


def _waiting_signal(reason: str, pod_name: str, container: str,
                    restart_count: int) -> tuple[str, Any]:
    """
    Map 1 K8s waiting reason → (signal_name enum, value đúng kiểu theo contract).
      - container_restart_count → value là int (số lần restart)
      - pod_oom_event           → value là string mô tả sự kiện
      - service_unhealthy       → value là string mô tả trạng thái
    Reason lạ → service_unhealthy (string) cho fail-safe (vẫn hợp enum).
    """
    signal_name, _ = _WAITING_REASON_MAP.get(reason, ("service_unhealthy", "UNKNOWN"))
    if signal_name == "container_restart_count":
        return signal_name, restart_count
    if signal_name == "pod_oom_event":
        return signal_name, (
            f"OOMKilled: Pod {pod_name}, Container {container}, Exit Code {_OOM_EXIT_CODE}"
        )
    return "service_unhealthy", f"{reason}: container {container} không khỏe mạnh"


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
        rc = cs.restart_count or 0
        # 1. waiting reason (CrashLoopBackOff, OOMKilled, ...) → enum signal_name
        if cs.state and cs.state.waiting:
            reason = cs.state.waiting.reason or ""
            mapped = _WAITING_REASON_MAP.get(reason)
            if mapped:
                fault_type = fault_type or mapped[1]
                signal_name, value = _waiting_signal(reason, pod.metadata.name, cs.name, rc)
                signals.append(_signal(service, namespace, deployment,
                                       signal_name, value, cfg.tenant_id))

        # 2. exit code 137 từ last terminated state → pod_oom_event (kể cả khi pod đã restart xong)
        if cs.last_state and cs.last_state.terminated:
            if cs.last_state.terminated.exit_code == _OOM_EXIT_CODE:
                fault_type = fault_type or "OOM_KILL"
                signals.append(_signal(
                    service, namespace, deployment, "pod_oom_event",
                    f"OOMKilled: Pod {pod.metadata.name}, Container {cs.name}, "
                    f"Exit Code {_OOM_EXIT_CODE}", cfg.tenant_id))

        # 3. restart count vượt ngưỡng → container_restart_count (kể cả khi pod đang Running)
        if rc > cfg.restart_count_threshold:
            fault_type = fault_type or "CRASH_LOOP"
            signals.append(_signal(service, namespace, deployment,
                                   "container_restart_count", rc, cfg.tenant_id))

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
        for cs in (pod.status.container_statuses or []):
            rc = cs.restart_count or 0
            # container_restart_count luôn báo → AI xác nhận restart KHÔNG tăng thêm (đã hồi phục)
            signals.append(_signal(service, namespace, deployment,
                                   "container_restart_count", rc, cfg.tenant_id))
            if cs.state and cs.state.waiting and cs.state.waiting.reason:
                # vẫn còn lỗi → phát signal lỗi đúng enum
                signal_name, value = _waiting_signal(
                    cs.state.waiting.reason, pod.metadata.name, cs.name, rc)
                signals.append(_signal(service, namespace, deployment,
                                       signal_name, value, cfg.tenant_id))
            elif not cs.ready or phase != "Running":
                # chưa ready / phase bất thường → service_unhealthy (string, hợp enum)
                signals.append(_signal(
                    service, namespace, deployment, "service_unhealthy",
                    f"container {cs.name} chưa ready (phase={phase})", cfg.tenant_id))
            # healthy (ready + Running + không waiting) → vắng tín hiệu lỗi = đã hồi phục
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
