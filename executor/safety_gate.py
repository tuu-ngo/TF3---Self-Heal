"""
Safety Gate (Lớp 1 — app-level) — chạy SAU /v1/decide, TRƯỚC execute (02_infra_design §8).
"action này có an toàn để execute không?"

Lưu ý: đây là lớp 1/3. Lớp 2 = K8s RBAC (verb-level), Lớp 3 = Kyverno (value-level).
Safety gate fail-closed: bất kỳ check nào fail → SafetyDenied(reason) → KHÔNG execute.

reason codes khớp audit (03_security_design §8, 07_test_eval TC-07..TC-11):
  denied_cross_tenant, denied_action_not_allowed, missing_verify_policy,
  missing_rollback_path, blast_radius_exceeded, invalid_pattern_type, scale_to_zero_denied
"""
from __future__ import annotations

from dataclasses import dataclass, field

from config import (
    ALLOWED_ACTIONS,
    CONFIG,
    DEFERRED_ACTIONS,
    URGENT_ACTIONS,
)
from errors import SafetyDenied
from models import ActionPlanItem, DecideResponse


@dataclass
class SafetyVerdict:
    allowed: bool
    reason: str = "safety_passed"
    checks_passed: list[str] = field(default_factory=list)


def check(decide: DecideResponse, incident_tenant_id: str,
          tenant_namespace: str, cfg=CONFIG) -> SafetyVerdict:
    """
    Validate toàn bộ action_plan. incident_tenant_id + tenant_namespace là context
    của incident (CDO biết từ alert), dùng để chặn cross-tenant kể cả khi AI trả sai target.
    Raise SafetyDenied nếu fail; trả SafetyVerdict(allowed=True) nếu pass.
    """
    passed: list[str] = []

    # 0. pattern_type hợp lệ
    if decide.pattern_type not in ("urgent", "deferred"):
        raise SafetyDenied("invalid_pattern_type", decide.pattern_type)
    passed.append("pattern_type_valid")

    # 1. verify_policy bắt buộc cho mọi mutating action (TC-10)
    if not decide.verify_policy or decide.verify_policy.window_seconds <= 0:
        raise SafetyDenied("missing_verify_policy")
    passed.append("verify_policy_present")

    if not decide.action_plan:
        raise SafetyDenied("missing_rollback_path", "empty action_plan")

    allowed_ns = set(decide.blast_radius_config.allowed_namespaces)

    for item in decide.action_plan:
        _check_action_allowed(item)
        _check_pattern_routing(item, decide.pattern_type)
        _check_tenant_match(item, tenant_namespace, allowed_ns)
        _check_blast_radius(item, decide, cfg)

    passed += [
        "action_allow_list", "pattern_routing",
        "tenant_match", "blast_radius",
    ]
    return SafetyVerdict(allowed=True, checks_passed=passed)


# ---------- per-action checks ----------

def _check_action_allowed(item: ActionPlanItem) -> None:
    # TC-08: action ngoài allow-list (vd DELETE_NAMESPACE) → deny
    if item.action not in ALLOWED_ACTIONS:
        raise SafetyDenied("denied_action_not_allowed", item.action)


def _check_pattern_routing(item: ActionPlanItem, pattern_type: str) -> None:
    # urgent action không được nằm trong deferred plan và ngược lại
    if pattern_type == "urgent" and item.action not in URGENT_ACTIONS:
        raise SafetyDenied("invalid_pattern_type", f"{item.action} không phải urgent")
    if pattern_type == "deferred" and item.action not in DEFERRED_ACTIONS:
        raise SafetyDenied("invalid_pattern_type", f"{item.action} không phải deferred")


def _check_tenant_match(item: ActionPlanItem, tenant_namespace: str,
                        allowed_ns: set[str]) -> None:
    # TC-07: incident thuộc tenant-a nhưng AI target tenant-b → deny cross-tenant
    target_ns = item.namespace
    if target_ns != tenant_namespace:
        raise SafetyDenied(
            "denied_cross_tenant",
            f"target ns={target_ns} ≠ incident ns={tenant_namespace}",
        )
    if target_ns not in allowed_ns:
        raise SafetyDenied(
            "denied_cross_tenant",
            f"target ns={target_ns} ngoài allowed_namespaces={sorted(allowed_ns)}",
        )


def _check_blast_radius(item: ActionPlanItem, decide: DecideResponse, cfg) -> None:
    p = item.params

    # SCALE_REPLICAS: 1 <= replicas <= max (Kyverno cũng chặn ở lớp 3, gate chặn trước)
    if item.action == "SCALE_REPLICAS":
        replicas = p.get("replicas")
        if replicas is None:
            raise SafetyDenied("blast_radius_exceeded", "SCALE_REPLICAS thiếu params.replicas")
        if replicas < cfg.min_replicas:
            raise SafetyDenied("scale_to_zero_denied", f"replicas={replicas}")
        if replicas > cfg.max_replicas:
            raise SafetyDenied("blast_radius_exceeded", f"replicas={replicas} > {cfg.max_replicas}")

    # PATCH_MEMORY_LIMIT: memory_limit_mb <= cap
    if item.action == "PATCH_MEMORY_LIMIT":
        mem = p.get("memory_limit_mb")
        if mem is None:
            raise SafetyDenied("blast_radius_exceeded", "PATCH_MEMORY_LIMIT thiếu memory_limit_mb")
        if mem > cfg.max_memory_mb:
            raise SafetyDenied("blast_radius_exceeded", f"memory={mem}MB > {cfg.max_memory_mb}MB")

    # blast-radius chung: % pod tác động
    if decide.blast_radius_config.max_pod_impact_pct > 100:
        raise SafetyDenied("blast_radius_exceeded", "max_pod_impact_pct > 100")
