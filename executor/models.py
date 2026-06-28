"""
Dataclass cho I/O schema theo ai-api-contract §3 (contract-new-4).
Chỉ parse các field CDO cần; additionalProperties bị bỏ qua an toàn.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------- /v1/detect ----------

@dataclass
class AnomalyContext:
    target_service: str
    suspected_fault_type: str
    system: str
    namespace: str | None = None
    deployment: str | None = None
    trigger_metric: str | None = None
    trigger_value: float | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AnomalyContext":
        return cls(
            target_service=d["target_service"],
            suspected_fault_type=d["suspected_fault_type"],
            system=d["system"],
            namespace=d.get("namespace"),
            deployment=d.get("deployment"),
            trigger_metric=d.get("trigger_metric"),
            trigger_value=d.get("trigger_value"),
        )

    def to_dict(self) -> dict[str, Any]:
        # /v1/decide yêu cầu echo lại FULL anomaly_context từ detect
        out = {
            "target_service": self.target_service,
            "suspected_fault_type": self.suspected_fault_type,
            "system": self.system,
        }
        for k in ("namespace", "deployment", "trigger_metric", "trigger_value"):
            v = getattr(self, k)
            if v is not None:
                out[k] = v
        return out


@dataclass
class DetectResponse:
    anomaly_detected: bool
    severity: float
    confidence: float
    reasoning: str
    correlation_id: str
    anomaly_context: AnomalyContext | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DetectResponse":
        ctx = d.get("anomaly_context")
        return cls(
            anomaly_detected=d["anomaly_detected"],
            severity=d["severity"],
            confidence=d["confidence"],
            reasoning=d["reasoning"],
            correlation_id=d["correlation_id"],
            anomaly_context=AnomalyContext.from_dict(ctx) if ctx else None,
        )


# ---------- /v1/decide ----------

@dataclass
class ActionPlanItem:
    step: int
    action: str
    target: str                      # "deployment/<name>"
    params: dict[str, Any]           # bắt buộc có namespace

    @property
    def namespace(self) -> str:
        return self.params["namespace"]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ActionPlanItem":
        return cls(step=d["step"], action=d["action"], target=d["target"], params=d["params"])


@dataclass
class BlastRadiusConfig:
    max_pod_impact_pct: int
    circuit_breaker_error_rate: float
    allowed_namespaces: list[str]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BlastRadiusConfig":
        return cls(
            max_pod_impact_pct=d["max_pod_impact_pct"],
            circuit_breaker_error_rate=d["circuit_breaker_error_rate"],
            allowed_namespaces=d["allowed_namespaces"],
        )


@dataclass
class VerifyPolicy:
    window_seconds: int
    success_conditions: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VerifyPolicy":
        return cls(window_seconds=d["window_seconds"], success_conditions=d.get("success_conditions", []))


@dataclass
class DecideResponse:
    matched_runbook: str
    pattern_type: str                # "urgent" | "deferred"
    action_plan: list[ActionPlanItem]
    blast_radius_config: BlastRadiusConfig
    verify_policy: VerifyPolicy
    correlation_id: str
    idempotency_key: str
    dry_run_mode: bool
    cost_cap_exceeded: bool = False
    # ⚠ contract-new-4: AI KHÔNG trả rollback_snapshot. CDO tự capture (snapshot.py).

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DecideResponse":
        return cls(
            matched_runbook=d["matched_runbook"],
            pattern_type=d["pattern_type"],
            action_plan=[ActionPlanItem.from_dict(x) for x in d["action_plan"]],
            blast_radius_config=BlastRadiusConfig.from_dict(d["blast_radius_config"]),
            verify_policy=VerifyPolicy.from_dict(d["verify_policy"]),
            correlation_id=d["correlation_id"],
            idempotency_key=d["idempotency_key"],
            dry_run_mode=d["dry_run_mode"],
            cost_cap_exceeded=d.get("cost_cap_exceeded", False),
        )


# ---------- /v1/verify ----------

@dataclass
class VerifyResponse:
    success: bool
    regression_detected: bool
    next_action: str                 # DONE | RETRY | ROLLBACK | ESCALATE
    escalation_bundle: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VerifyResponse":
        return cls(
            success=d["success"],
            regression_detected=d["regression_detected"],
            next_action=d["next_action"],
            escalation_bundle=d.get("escalation_bundle"),
        )


# ---------- snapshot CDO tự capture trước execute ----------

@dataclass
class RollbackSnapshot:
    """CDO tự capture TRƯỚC execute (contract-new-4 — AI không trả về)."""
    pattern_type: str
    captured_at: str
    # urgent path
    k8s_state: dict[str, Any] | None = None      # {memory_limit, replica_count, image_tag}
    # deferred path
    git_sha: str | None = None
