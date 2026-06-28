"""
Rollback snapshot — CDO TỰ capture TRƯỚC execute (contract-new-4: AI không trả rollback_snapshot).
  urgent  → đọc K8s API current state (memory_limit, replica_count, image_tag)
  deferred → ghi Git commit SHA hiện tại của manifest repo
Snapshot được lưu vào audit log; dùng khi /v1/verify trả next_action=ROLLBACK.
"""
from __future__ import annotations

import time

from k8s_client import K8sClient
from models import DecideResponse, RollbackSnapshot


def capture(decide: DecideResponse, k8s: K8sClient) -> RollbackSnapshot:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if decide.pattern_type == "urgent":
        # snapshot state của (các) target trước khi patch
        first = decide.action_plan[0]
        ns = first.namespace                      # từ params.namespace (bắt buộc)
        _, _, name = first.target.partition("/")  # "deployment/<name>"
        state = k8s.get_deployment_state(ns, name)
        return RollbackSnapshot(pattern_type="urgent", captured_at=now, k8s_state=state)

    # deferred: ghi git SHA hiện tại
    return RollbackSnapshot(pattern_type="deferred", captured_at=now, git_sha=_current_git_sha())


def _current_git_sha() -> str:
    # TODO(W12): đọc HEAD SHA của manifest repo (subprocess git rev-parse HEAD)
    return "MOCK_SHA_HEAD"
