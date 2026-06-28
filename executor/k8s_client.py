"""
Wrapper mỏng quanh Kubernetes client cho urgent path.
SKELETON: signature đầy đủ + server-side dry-run; cần `kubernetes` lib + kubeconfig/in-cluster.

Quyền RBAC khớp deployment-contract §3.D (get/list/patch deployments, pods, replicasets...).
KHÔNG có verb delete deployment/namespace.
"""
from __future__ import annotations

from typing import Any

from config import CONFIG

try:
    from kubernetes import client
    from kubernetes import config as k8s_config
    _HAS_K8S = True
except ImportError:
    _HAS_K8S = False


class K8sClient:
    def __init__(self, in_cluster: bool = True, cfg=CONFIG):
        # enabled=False → mọi call trả stub (mock). Bật khi có lib VÀ không ở mock mode.
        self.enabled = _HAS_K8S and not cfg.k8s_mock
        if not self.enabled:
            return
        if in_cluster:
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
        # restart = patch annotation kubectl.kubernetes.io/restartedAt
        # TODO(W12): body patch + dry_run="All" cho server-side dry-run
        return self._stub("RESTART_DEPLOYMENT", namespace, name, dry_run)

    def patch_memory_limit(self, namespace: str, name: str, container: str,
                           request_mb: int | None, limit_mb: int, dry_run: bool = False) -> dict:
        # TODO(W12): strategic-merge patch resources.limits/requests.memory
        return self._stub("PATCH_MEMORY_LIMIT", namespace, name, dry_run, container=container)

    def rollout_undo(self, namespace: str, name: str, dry_run: bool = False) -> dict:
        # TODO(W12): patch về previous ReplicaSet revision
        return self._stub("ROLLOUT_UNDO", namespace, name, dry_run)

    def _stub(self, action: str, ns: str, name: str, dry_run: bool, **extra) -> dict:
        return {"action": action, "namespace": ns, "name": name,
                "dry_run": dry_run, "status": "MOCK_OK" if not self.enabled else "OK", **extra}
