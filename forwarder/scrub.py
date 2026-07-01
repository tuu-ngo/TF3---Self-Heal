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


def scrub_text(text: str) -> str:
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


def scrub_signal(signal: dict[str, Any]) -> dict[str, Any]:
    """Scrub value (nếu string) + label string. Trả signal mới (không mutate gốc)."""
    s = dict(signal)
    if isinstance(s.get("value"), str):
        s["value"] = scrub_text(s["value"])
    labels = s.get("labels")
    if isinstance(labels, dict):
        s["labels"] = {k: (scrub_text(v) if isinstance(v, str) else v)
                       for k, v in labels.items()}
    return s
