"""
Idempotency lock — DynamoDB atomic conditional write (deployment-contract §4.A).
CHỈ áp dụng cho /v1/decide (endpoint duy nhất có side-effect). TTL 24h.

SKELETON: logic conditional write đã có; cần boto3 + table thật để chạy W12.
Dev mode (không có table) → dùng set in-memory.
"""
from __future__ import annotations

import time

from config import CONFIG

try:
    import boto3
    from botocore.exceptions import ClientError
    _HAS_BOTO = True
except ImportError:  # dev không cài boto3
    _HAS_BOTO = False


class IdempotencyLock:
    def __init__(self, cfg=CONFIG):
        self.cfg = cfg
        self._mem: set[str] = set()  # fallback dev
        self._table = None
        if _HAS_BOTO and cfg.audit_bucket:  # dùng audit_bucket như cờ "đang chạy AWS thật"
            self._table = boto3.resource("dynamodb", region_name=cfg.aws_region).Table(
                cfg.idempotency_table
            )

    def acquire(self, idempotency_key: str) -> bool:
        """
        True nếu lock chiếm thành công (key chưa tồn tại) → tiến hành.
        False nếu key đã tồn tại (409 Conflict) → KHÔNG execute lại.
        """
        if self._table is None:
            if idempotency_key in self._mem:
                return False
            self._mem.add(idempotency_key)
            return True

        expires_at = int(time.time()) + self.cfg.idempotency_ttl_seconds
        try:
            self._table.put_item(
                Item={"idempotency_key": idempotency_key, "expires_at": expires_at},
                ConditionExpression="attribute_not_exists(idempotency_key)",
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
