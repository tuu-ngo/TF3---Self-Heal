"""
Exception types map theo HTTP error codes của ai-api-contract §4.
Phân biệt rõ retryable vs non-retryable để main loop xử đúng.
"""
from __future__ import annotations


class AIError(Exception):
    """Base cho mọi lỗi khi gọi AI endpoint."""
    audit_reason: str = "ai_error"


class AIBadRequest(AIError):           # 400 — schema sai, KHÔNG retry
    audit_reason = "ai_bad_request"


class AIUnauthorized(AIError):         # 401 — Local Trust/mTLS sai, KHÔNG retry
    audit_reason = "auth_config_error"


class AITenantMismatch(AIError):       # 403 — X-Tenant-Id ≠ tenant_id payload, KHÔNG retry
    audit_reason = "tenant_mismatch"


class AIConflict(AIError):             # 409 — trùng Idempotency-Key
    audit_reason = "idempotency_duplicate_denied"


class AIRateLimited(AIError):          # 429 — backoff theo Retry-After
    audit_reason = "ai_rate_limited"

    def __init__(self, retry_after_s: float = 1.0):
        super().__init__(f"rate limited, retry after {retry_after_s}s")
        self.retry_after_s = retry_after_s


class AIInternalError(AIError):        # 500 — retry tối đa 2 lần rồi escalate
    audit_reason = "ai_internal_error"


class AIUnavailable(AIError):          # 503 — upstream down, escalate, KHÔNG execute
    audit_reason = "ai_unavailable_escalated"


class SafetyDenied(Exception):
    """Safety gate từ chối action. reason là machine-readable (vào audit)."""
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}".strip(": "))
        self.reason = reason
        self.detail = detail
