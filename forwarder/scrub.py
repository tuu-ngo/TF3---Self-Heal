"""
PII scrubbing — che thông tin nhạy cảm trong telemetry TRƯỚC khi vào SQS/audit.
Yêu cầu SOC2 (03_security_design): log/telemetry không được chứa PII/secret thô.
Áp cho `value` (log message/event) + label string. Idempotent, không crash.
"""
from __future__ import annotations

import re
from typing import Any

# 7 pattern (khớp mức CDO-01): email · credit-card · SSN · AWS access-key ·
# AWS secret-key · bearer/JWT token · password/secret=... assignment.
_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<EMAIL>"),
    (re.compile(r"\b(?:\d[ -]*?){13,16}\b"), "<CARD>"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "<SSN>"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<AWS_AKID>"),
    (re.compile(r"\baws_secret_access_key\s*[:=]\s*\S+", re.I), "aws_secret_access_key=<REDACTED>"),
    (re.compile(r"\b(?:Bearer\s+|eyJ)[A-Za-z0-9._-]{20,}"), "<TOKEN>"),
    (re.compile(r"\b(pass(word)?|secret|token|api[_-]?key)\s*[:=]\s*\S+", re.I),
     r"\1=<REDACTED>"),
]


# Key-name based scrub — bắt secret NGAY CẢ khi value không khớp regex nào
# (vd token định dạng lạ, password không có prefix). Nếu tên key nhạy cảm →
# redact toàn bộ value. Bổ sung lớp phòng thủ ngoài 7 regex ở trên.
_REDACTED = "<REDACTED>"
_SENSITIVE_KEYS: frozenset[str] = frozenset({
    "password", "passwd", "pwd", "secret", "secret_key", "secretkey",
    "api_key", "apikey", "token", "auth_token", "access_token",
    "refresh_token", "authorization", "credential", "credentials",
    "aws_secret_access_key", "aws_access_key_id", "private_key", "ssh_key",
})


def _is_sensitive_key(key: str) -> bool:
    kn = key.lower().replace("-", "_")
    return any(sk in kn for sk in _SENSITIVE_KEYS)


def scrub_text(text: str) -> str:
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


def scrub_value(key: str, value: Any) -> Any:
    """Redact theo TÊN KEY nhạy cảm (bất kể format); còn lại scrub regex nếu string."""
    if _is_sensitive_key(key):
        return _REDACTED
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {k: scrub_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_value(key, v) for v in value]
    return value


def scrub_signal(signal: dict[str, Any]) -> dict[str, Any]:
    """Scrub value (regex nếu string) + label (regex + key-name). Không mutate gốc."""
    s = dict(signal)
    if isinstance(s.get("value"), str):
        s["value"] = scrub_text(s["value"])
    labels = s.get("labels")
    if isinstance(labels, dict):
        s["labels"] = {k: scrub_value(k, v) for k, v in labels.items()}
    return s
