"""
Urgent executor (Path B) — CDO gọi Kubernetes API trực tiếp. RTO target < 60s.
Quy trình: server-side dry-run trước → nếu pass thì execute thật.
SKELETON: wiring đầy đủ; mapping action→K8s call dùng K8sClient (cần lib W12).
"""
from __future__ import annotations

import time

from k8s_client import K8sClient
from models import ActionPlanItem, DecideResponse

from .base import ActionExecutor, ExecutionResult


class UrgentExecutor(ActionExecutor):
    def __init__(self, k8s: K8sClient | None = None):
        self.k8s = k8s or K8sClient(in_cluster=False)

    def execute(self, decide: DecideResponse) -> ExecutionResult:
        item = decide.action_plan[0]  # MVP: xử bước 1; mở rộng loop nhiều step sau
        start = time.time()

        # 1. server-side dry-run trước (TC-13: dry-run fail → KHÔNG execute thật)
        dry = self._dispatch(item, dry_run=True)
        if dry.get("status") not in ("OK", "MOCK_OK"):
            return ExecutionResult(item.action, item.target, "FAILED",
                                   detail={"phase": "dry_run", **dry})

        # 2. execute thật
        real = self._dispatch(item, dry_run=False)
        status = "COMPLETED" if real.get("status") in ("OK", "MOCK_OK") else "FAILED"
        return ExecutionResult(
            action=item.action, target=item.target, status=status,
            execution_time_seconds=int(time.time() - start), detail=real,
        )

    def rollback(self, decide: DecideResponse, snapshot) -> ExecutionResult:
        # urgent rollback: kubectl rollout undo hoặc apply ngược k8s_state đã snapshot
        item = decide.action_plan[0]
        ns, name = _ns_name(item)
        res = self.k8s.rollout_undo(ns, name)
        status = "COMPLETED" if res.get("status") in ("OK", "MOCK_OK") else "FAILED"
        return ExecutionResult(item.action, item.target, status, detail={"rollback": res})

    def _dispatch(self, item: ActionPlanItem, dry_run: bool) -> dict:
        ns, name = _ns_name(item)
        p = item.params
        if item.action == "RESTART_DEPLOYMENT":
            return self.k8s.restart_deployment(ns, name, dry_run=dry_run)
        if item.action == "PATCH_MEMORY_LIMIT":
            return self.k8s.patch_memory_limit(
                ns, name, container=p.get("container", "main"),
                request_mb=p.get("memory_request_mb"), limit_mb=p["memory_limit_mb"],
                dry_run=dry_run,
            )
        if item.action == "ROLLOUT_UNDO":
            return self.k8s.rollout_undo(ns, name, dry_run=dry_run)
        return {"status": "FAILED", "reason": f"unsupported urgent action {item.action}"}


def _ns_name(item: ActionPlanItem) -> tuple[str, str]:
    _, _, name = item.target.partition("/")   # "deployment/<name>"
    return item.namespace, name
