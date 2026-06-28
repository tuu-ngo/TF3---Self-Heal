"""
Safety gate unit test — pytest-compatible, chạy không cần server/cluster.
    pytest -q --cov=safety_gate            # CI (Cửa 2)
    python tests/test_safety_gate.py       # chạy tay
Cover các nhánh deny quan trọng cho rubric (TC-07/08/10/blast/routing).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from errors import SafetyDenied  # noqa: E402
from models import DecideResponse  # noqa: E402
from safety_gate import check  # noqa: E402

TENANT = "6c8b4b2b-4d45-4209-a1b4-4b532d56a31c"


def _decide(action="RESTART_DEPLOYMENT", pattern="urgent", ns="tenant-a",
            params=None, allowed=None, window=120):
    return DecideResponse.from_dict({
        "matched_runbook": "R", "pattern_type": pattern,
        "action_plan": [{"step": 1, "action": action,
                         "target": "deployment/cdo-sample-api",
                         "params": {"namespace": ns, **(params or {})}}],
        "blast_radius_config": {"max_pod_impact_pct": 25, "circuit_breaker_error_rate": 0.2,
                                "allowed_namespaces": allowed or ["tenant-a"]},
        "verify_policy": {"window_seconds": window},
        "correlation_id": "c", "idempotency_key": "k", "dry_run_mode": False,
    })


def _expect_deny(reason, **kw):
    try:
        check(_decide(**kw), TENANT, "tenant-a")
    except SafetyDenied as d:
        assert d.reason == reason, f"expected {reason}, got {d.reason}"
        return
    raise AssertionError(f"expected deny {reason}, but passed")


# ---------- test cases (pytest collect theo prefix test_) ----------

def test_valid_urgent_passes():
    v = check(_decide(), TENANT, "tenant-a")
    assert v.allowed


def test_cross_tenant_denied():           # TC-07
    _expect_deny("denied_cross_tenant", ns="tenant-b", allowed=["tenant-b"])


def test_action_not_in_allow_list():      # TC-08
    _expect_deny("denied_action_not_allowed", action="DELETE_NAMESPACE")


def test_missing_verify_policy():         # TC-10
    _expect_deny("missing_verify_policy", window=0)


def test_scale_to_zero_denied():
    _expect_deny("scale_to_zero_denied", action="SCALE_REPLICAS",
                 pattern="deferred", params={"replicas": 0})


def test_blast_radius_replicas():
    _expect_deny("blast_radius_exceeded", action="SCALE_REPLICAS",
                 pattern="deferred", params={"replicas": 50})


def test_blast_radius_memory():
    _expect_deny("blast_radius_exceeded", action="PATCH_MEMORY_LIMIT",
                 params={"memory_limit_mb": 8192, "container": "main"})


def test_pattern_routing_mismatch():
    _expect_deny("invalid_pattern_type", action="SCALE_REPLICAS",
                 pattern="urgent", params={"replicas": 3})


_ALL = [
    test_valid_urgent_passes, test_cross_tenant_denied, test_action_not_in_allow_list,
    test_missing_verify_policy, test_scale_to_zero_denied, test_blast_radius_replicas,
    test_blast_radius_memory, test_pattern_routing_mismatch,
]


if __name__ == "__main__":
    for t in _ALL:
        t()
    print(f"OK — {len(_ALL)}/{len(_ALL)} safety gate cases passed")
