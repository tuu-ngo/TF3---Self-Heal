"""
Wrapper mỏng quanh Kubernetes client cho urgent path.
SKELETON: signature đầy đủ + server-side dry-run; cần `kubernetes` lib + kubeconfig/in-cluster.

Quyền RBAC khớp deployment-contract §3.D (get/list/patch deployments, pods, replicasets...).
KHÔNG có verb delete deployment/namespace.
"""
from __future__ import annotations

import time
from typing import Any

from config import CONFIG

try:
    from kubernetes import client
    from kubernetes import config as k8s_config
    from kubernetes.client.rest import ApiException
    _HAS_K8S = True
except ImportError:
    _HAS_K8S = False


class K8sClient:
    def __init__(self, in_cluster: bool = True, cfg=CONFIG):
        # enabled=False → mọi call trả stub (mock). Bật khi có lib VÀ không ở mock mode.
        self.enabled = _HAS_K8S and not cfg.k8s_mock
        if not self.enabled:
            return
        # Auto-detect: trong pod (có KUBERNETES_SERVICE_HOST) → in-cluster config (SA token);
        # local dev → kubeconfig. Bỏ qua tham số in_cluster để robust khi deploy thật.
        import os
        if os.environ.get("KUBERNETES_SERVICE_HOST"):
            k8s_config.load_incluster_config()
        else:
            k8s_config.load_kube_config()
        self.apps = client.AppsV1Api()
        self.core = client.CoreV1Api()

    # ---------- đọc state cho snapshot ----------

    def get_deployment_state(self, namespace: str, name: str) -> dict[str, Any]:
        """Đọc current state để snapshot TRƯỚC khi patch (memory_limit, replicas, image)."""
        if not self.enabled:
            return {"_mock": True, "namespace": namespace, "name": name}
        dep = self.apps.read_namespaced_deployment(name, namespace)
        container = dep.spec.template.spec.containers[0]
        limits = (container.resources.limits or {}) if container.resources else {}
        return {
            "replica_count": dep.spec.replicas,
            "image_tag": container.image,
            "memory_limit": limits.get("memory"),
            "revision": dep.metadata.annotations.get("deployment.kubernetes.io/revision"),
        }

    # ---------- mutating actions (urgent) ----------

    def restart_deployment(self, namespace: str, name: str, dry_run: bool = False) -> dict:
        # restart = patch annotation kubectl.kubernetes.io/restartedAt → rolling restart pod
        if not self.enabled:
            return self._stub("RESTART_DEPLOYMENT", namespace, name, dry_run)
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        body = {
            "spec": {"template": {"metadata": {"annotations": {
                "kubectl.kubernetes.io/restartedAt": ts,
            }}}}
        }
        return self._patch_deployment("RESTART_DEPLOYMENT", namespace, name, body, dry_run)

    def patch_memory_limit(self, namespace: str, name: str, container: str,
                           request_mb: int | None, limit_mb: int, dry_run: bool = False) -> dict:
        # strategic-merge patch: container khớp theo name → chỉ sửa resources.memory
        if not self.enabled:
            return self._stub("PATCH_MEMORY_LIMIT", namespace, name, dry_run, container=container)
        resources: dict[str, Any] = {"limits": {"memory": f"{limit_mb}Mi"}}
        if request_mb:
            resources["requests"] = {"memory": f"{request_mb}Mi"}
        body = {
            "spec": {"template": {"spec": {"containers": [
                {"name": container, "resources": resources},
            ]}}}
        }
        return self._patch_deployment("PATCH_MEMORY_LIMIT", namespace, name, body, dry_run,
                                      container=container)

    def rollout_undo(self, namespace: str, name: str, dry_run: bool = False) -> dict:
        # undo = copy pod template của ReplicaSet revision trước → patch lại deployment
        if not self.enabled:
            return self._stub("ROLLOUT_UNDO", namespace, name, dry_run)
        try:
            dep = self.apps.read_namespaced_deployment(name, namespace)
            cur_rev = int((dep.metadata.annotations or {}).get(
                "deployment.kubernetes.io/revision", "0"))
            prev_rs = self._previous_replicaset(namespace, dep.metadata.uid, cur_rev)
            if prev_rs is None:
                return {"status": "FAILED", "action": "ROLLOUT_UNDO",
                        "reason": "không có revision trước để rollback"}
            template = self.apps.api_client.sanitize_for_serialization(prev_rs.spec.template)
            # bỏ pod-template-hash để Deployment tự sinh hash mới cho ReplicaSet
            labels = template.get("metadata", {}).get("labels", {})
            labels.pop("pod-template-hash", None)
            body = {"spec": {"template": template}}
            return self._patch_deployment("ROLLOUT_UNDO", namespace, name, body, dry_run,
                                          rolled_back_to_revision=int(
                                              (prev_rs.metadata.annotations or {}).get(
                                                  "deployment.kubernetes.io/revision", "-1")))
        except ApiException as e:
            return {"status": "FAILED", "action": "ROLLOUT_UNDO",
                    "reason": f"k8s api error {e.status}: {e.reason}"}

    # ---------- internals ----------

    def _patch_deployment(self, action: str, namespace: str, name: str,
                          body: dict, dry_run: bool, **extra) -> dict:
        """Strategic-merge patch deployment. dry_run=True → server-side dry-run ('All')."""
        try:
            self.apps.patch_namespaced_deployment(
                name=name, namespace=namespace, body=body,
                dry_run="All" if dry_run else None,
            )
            return {"status": "OK", "action": action, "namespace": namespace,
                    "name": name, "dry_run": dry_run, **extra}
        except ApiException as e:
            return {"status": "FAILED", "action": action, "namespace": namespace,
                    "name": name, "dry_run": dry_run,
                    "reason": f"k8s api error {e.status}: {e.reason}", **extra}

    def _previous_replicaset(self, namespace: str, dep_uid: str, cur_rev: int):
        """Tìm ReplicaSet thuộc deployment có revision lớn nhất < cur_rev."""
        rs_list = self.apps.list_namespaced_replica_set(namespace)
        best = None
        best_rev = -1
        for rs in rs_list.items:
            if not any(ref.uid == dep_uid for ref in (rs.metadata.owner_references or [])):
                continue
            rev = int((rs.metadata.annotations or {}).get(
                "deployment.kubernetes.io/revision", "-1"))
            if best_rev < rev < cur_rev:
                best_rev, best = rev, rs
        return best

    def list_pods_raw(self, namespace: str):
        """
        List namespaced pods. Trả về V1PodList hoặc None nếu mock mode.
        Dùng bởi watcher.py để poll pod container status.
        """
        if not self.enabled:
            return None
        return self.core.list_namespaced_pod(namespace)

    def get_recent_pod_logs(self, namespace: str, deployment: str,
                            tail_lines: int = 20) -> list[str]:
        """
        Best-effort: log gần nhất của pod thuộc deployment, cho escalation bundle.
        RBAC: pods/log get (executor-rbac.yaml). Mock mode → [].
        """
        if not self.enabled:
            return []
        out: list[str] = []
        pods = self.core.list_namespaced_pod(namespace)
        for pod in pods.items:
            name = pod.metadata.name
            if not (name.startswith(deployment) or
                    (pod.metadata.labels or {}).get("app") == deployment):
                continue
            try:
                txt = self.core.read_namespaced_pod_log(
                    name, namespace, tail_lines=tail_lines)
                out.append(f"[{name}] {txt.strip()}")
            except ApiException:
                continue
        return out

    def _stub(self, action: str, ns: str, name: str, dry_run: bool, **extra) -> dict:
        return {"action": action, "namespace": ns, "name": name,
                "dry_run": dry_run, "status": "MOCK_OK" if not self.enabled else "OK", **extra}
