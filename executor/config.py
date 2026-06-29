"""
Cấu hình executor — đọc từ env, có default an toàn cho dev.
Mọi hằng số bám theo contract-new-4 (ai-api / deployment / telemetry).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# Action enum cố định theo ai-api-contract §3.2 (DecideResponse.action_plan[].action)
ALLOWED_ACTIONS: frozenset[str] = frozenset({
    "RESTART_DEPLOYMENT",
    "PATCH_MEMORY_LIMIT",
    "SCALE_REPLICAS",
    "ROLLOUT_UNDO",
    "ROTATE_SECRET",
})

# urgent → CDO gọi K8s API trực tiếp; deferred → Git commit → ArgoCD sync
URGENT_ACTIONS: frozenset[str] = frozenset({
    "RESTART_DEPLOYMENT", "PATCH_MEMORY_LIMIT", "ROLLOUT_UNDO",
})
DEFERRED_ACTIONS: frozenset[str] = frozenset({
    "SCALE_REPLICAS", "ROTATE_SECRET",
})


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    return int(os.environ.get(key, default))


def _env_float(key: str, default: float) -> float:
    return float(os.environ.get(key, default))


@dataclass(frozen=True)
class Config:
    # --- Tenant / AI endpoint ---
    tenant_id: str = _env("CDO_TENANT_ID", "6c8b4b2b-4d45-4209-a1b4-4b532d56a31c")
    ai_base_url: str = _env(
        "AI_BASE_URL",
        "http://ai-engine.self-heal-system.svc.cluster.local:8080",
    )
    ai_timeout_detect_s: float = _env_float("AI_TIMEOUT_DETECT_S", 1.0)   # SLA p99 < 300ms
    ai_timeout_decide_s: float = _env_float("AI_TIMEOUT_DECIDE_S", 4.0)   # SLA p99 < 3000ms (LLM)
    ai_timeout_verify_s: float = _env_float("AI_TIMEOUT_VERIFY_S", 1.5)   # SLA p99 < 500ms
    dry_run_mode: bool = _env("CDO_DRY_RUN", "false").lower() == "true"

    # --- Namespace / executor identity ---
    # ⚠ Contract §3.D yêu cầu SA `tf3-cdo-controller` ở `self-heal-system`.
    #   Thiết kế hiện đặt executor ở `platform` — chốt trước W12 T1 (xem 03_security_design §5).
    executor_namespace: str = _env("CDO_EXECUTOR_NS", "self-heal-system")
    # Mock K8s (Day-1 offline test không cần cluster thật, kể cả khi `kubernetes` lib đã cài)
    k8s_mock: bool = _env("CDO_K8S_MOCK", "false").lower() == "true"
    tenant_namespaces: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            _env("CDO_TENANT_NAMESPACES", "tenant-a,tenant-b").split(",")
        )
    )

    # --- Pre-Decide Gate thresholds (02_infra_design §5, step 5) ---
    confidence_discard_below: float = _env_float("GATE_CONF_DISCARD", 0.5)
    confidence_execute_at: float = _env_float("GATE_CONF_EXECUTE", 0.8)
    flap_window_seconds: int = _env_int("GATE_FLAP_WINDOW_S", 600)        # 10 phút
    flap_threshold: int = _env_int("GATE_FLAP_THRESHOLD", 3)             # lần 3+ → escalate

    # --- Safety Gate / blast-radius caps (khớp Kyverno policy) ---
    max_replicas: int = _env_int("SAFETY_MAX_REPLICAS", 10)
    max_memory_mb: int = _env_int("SAFETY_MAX_MEMORY_MB", 4096)          # 4Gi
    min_replicas: int = _env_int("SAFETY_MIN_REPLICAS", 1)              # cấm scale-to-0

    # --- AWS resources ---
    aws_region: str = _env("AWS_REGION", "us-east-1")
    idempotency_table: str = _env("CDO_IDEMPOTENCY_TABLE", "cdo-idempotency-dev")
    idempotency_ttl_seconds: int = _env_int("CDO_IDEMPOTENCY_TTL_S", 86400)  # 24h
    audit_bucket: str = _env("CDO_AUDIT_BUCKET", "")  # rỗng → audit chỉ ra stdout (dev)

    # --- Pod Status Watcher (Option 1 telemetry collector) ---
    poll_interval_s: int = _env_int("CDO_POLL_INTERVAL_S", 30)
    restart_count_threshold: int = _env_int("CDO_RESTART_THRESHOLD", 3)
    heal_cooldown_s: int = _env_int("CDO_HEAL_COOLDOWN_S", 300)  # tránh trigger lại trong 5 phút
    verify_max_wait_s: int = _env_int("CDO_VERIFY_MAX_WAIT_S", 120)  # cap chờ trước khi scrape verify

    # --- Circuit Breaker (safety sub-checkpoint #5) ---
    circuit_fail_threshold: int = _env_int("CDO_CIRCUIT_THRESHOLD", 3)   # fail liên tiếp → trip
    circuit_window_s: int = _env_int("CDO_CIRCUIT_WINDOW_S", 300)        # cửa sổ đếm fail
    circuit_cooldown_s: int = _env_int("CDO_CIRCUIT_COOLDOWN_S", 300)    # thời gian open trước half-open

    # --- Escalation delivery (req #8) ---
    escalation_webhook_url: str = _env("CDO_ESCALATION_WEBHOOK", "")  # rỗng → mock pager (chỉ audit)

    # --- Error/retry policy (ai-api-contract §4) ---
    http_500_max_retries: int = 2
    http_500_backoff_s: tuple[float, ...] = (1.0, 3.0)


CONFIG = Config()
