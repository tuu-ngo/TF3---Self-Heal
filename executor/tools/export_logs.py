"""
Export LOG THẬT từ các service (Online Boutique) cho AI team → logs.csv.

Định dạng bám dataset engine: cột `timestamp` (epoch ns), `service`, `level`, `message`.
Nguồn = `kubectl logs --timestamps`. Xử cả log JSON (frontend/checkoutservice — field
severity/message) lẫn plain-text.

    python executor/tools/export_logs.py > data-export/online_boutique_logs.csv

Env:
    LOG_NS      (default tenant-a)
    LOG_SVCS    (CSV; default = các service Online Boutique)
    LOG_SINCE   (default 15m)   LOG_TAIL (default 2000/service)
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import subprocess
import sys

NS = os.getenv("LOG_NS", "tenant-a")
SINCE = os.getenv("LOG_SINCE", "15m")
TAIL = os.getenv("LOG_TAIL", "2000")
DEFAULT_SVCS = (
    "frontend,checkoutservice,cartservice,paymentservice,recommendationservice,"
    "productcatalogservice,shippingservice,currencyservice,emailservice,adservice"
)
SVCS = [s.strip() for s in os.getenv("LOG_SVCS", DEFAULT_SVCS).split(",") if s.strip()]


def parse(msg: str) -> tuple[str, str]:
    """(level, message) — hỗ trợ JSON log (severity/message) + plain-text."""
    try:
        j = json.loads(msg)
        lvl = str(j.get("severity") or j.get("level") or "info").upper()
        text = str(j.get("message") or j.get("msg") or msg)
        return lvl, text
    except (ValueError, TypeError):
        return "INFO", msg


def main() -> None:
    w = csv.writer(sys.stdout)
    w.writerow(["timestamp", "service", "level", "message"])
    total = 0
    for svc in SVCS:
        try:
            out = subprocess.run(
                ["kubectl", "-n", NS, "logs", f"deploy/{svc}",
                 "--timestamps", f"--since={SINCE}", f"--tail={TAIL}"],
                capture_output=True, text=True, timeout=90,
            ).stdout
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"{svc}: {exc}\n")
            continue
        for line in out.splitlines():
            if " " not in line:
                continue
            tstr, _, msg = line.partition(" ")
            try:
                ep = int(dt.datetime.fromisoformat(tstr.replace("Z", "+00:00")).timestamp() * 1e9)
            except (ValueError, TypeError):
                ep = ""
            lvl, text = parse(msg)
            w.writerow([ep, svc, lvl, text[:500]])
            total += 1
    sys.stderr.write(f"[export_logs] {total} dòng từ {len(SVCS)} service (ns={NS})\n")


if __name__ == "__main__":
    main()
