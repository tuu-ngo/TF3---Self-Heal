"""Cấu hình pytest cho package executor.

Đặt thư mục `executor/` lên đầu sys.path để mọi test trong `tests/` import được
các module anh em (circuit_breaker, safety_gate, models, ...) bằng tên trực tiếp,
bất kể pytest được gọi từ đâu.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
