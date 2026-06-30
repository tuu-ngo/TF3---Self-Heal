#!/usr/bin/env python3
"""Normalize mock or real telemetry into the frozen telemetry contract.

Examples:
  python normalize_telemetry.py auto --input raw.json
  python normalize_telemetry.py scenario --input ../../../TF3-Self-Heal-Agent-AWS/executor/scenarios/sc01_oom_kill_a.json
  python normalize_telemetry.py prometheus --input prom_query.json --signal-name service_latency_p95 --service checkout-svc --namespace tenant-a --deployment cdo-sample-api
  python normalize_telemetry.py k8s-events --input k8s_events.json
  python normalize_telemetry.py logs --input raw_logs.json
  python normalize_telemetry.py otel-spans --input spans.json
  python normalize_telemetry.py validate --input telemetry_window.json
"""
from __future__ import annotations

import argparse
import json
import sys

from telemetry_contract import (
    TelemetryContractError,
    auto_normalize,
    from_kubernetes_events,
    from_log_events,
    from_otel_export,
    from_otel_spans,
    from_prometheus_result,
    normalize_window,
    validate_window,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize Team C telemetry inputs.")
    sub = parser.add_subparsers(dest="mode", required=True)

    auto = sub.add_parser("auto", help="Auto-detect raw telemetry shape and normalize it.")
    auto.add_argument("--input", required=True)
    auto.add_argument("--output")

    scenario = sub.add_parser("scenario", help="Normalize executor scenario JSON telemetry_window.")
    scenario.add_argument("--input", required=True)
    scenario.add_argument("--output")
    scenario.add_argument("--window-only", action="store_true")

    prometheus = sub.add_parser("prometheus", help="Normalize Prometheus HTTP API JSON.")
    prometheus.add_argument("--input", required=True)
    prometheus.add_argument("--output")
    prometheus.add_argument("--signal-name", required=True)
    prometheus.add_argument("--service", required=True)
    prometheus.add_argument("--namespace", required=True)
    prometheus.add_argument("--deployment", required=True)

    events = sub.add_parser("k8s-events", help="Normalize kubectl get events -o json output.")
    events.add_argument("--input", required=True)
    events.add_argument("--output")

    logs = sub.add_parser("logs", help="Normalize raw log event, log list, or CloudWatch logEvents JSON.")
    logs.add_argument("--input", required=True)
    logs.add_argument("--output")

    spans = sub.add_parser("otel-spans", help="Normalize simplified OpenTelemetry span list JSON.")
    spans.add_argument("--input", required=True)
    spans.add_argument("--output")

    otlp = sub.add_parser("otlp-export", help="Normalize OTLP JSON export with resourceSpans.")
    otlp.add_argument("--input", required=True)
    otlp.add_argument("--output")

    validate = sub.add_parser("validate", help="Validate telemetry_window[] or scenario JSON after normalization.")
    validate.add_argument("--input", required=True)

    args = parser.parse_args()
    try:
        if args.mode == "auto":
            result = auto_normalize(_load(args.input))
        elif args.mode == "scenario":
            payload = _load(args.input)
            normalized = normalize_window(payload["telemetry_window"], "mock_scenario")
            result = normalized if args.window_only else {**payload, "telemetry_window": normalized}
        elif args.mode == "prometheus":
            payload = _load(args.input)
            result = from_prometheus_result(
                payload,
                args.signal_name,
                args.service,
                args.namespace,
                args.deployment,
            )
        elif args.mode == "k8s-events":
            result = from_kubernetes_events(_load(args.input))
        elif args.mode == "logs":
            payload = _load(args.input)
            if isinstance(payload, dict) and "logEvents" in payload:
                result = from_log_events(payload["logEvents"], payload)
            elif isinstance(payload, list):
                result = from_log_events(payload)
            else:
                result = from_log_events([payload])
        elif args.mode == "otel-spans":
            payload = _load(args.input)
            if not isinstance(payload, list):
                raise TelemetryContractError("otel-spans input must be a JSON list")
            result = from_otel_spans(payload)
        elif args.mode == "otlp-export":
            result = from_otel_export(_load(args.input))
        elif args.mode == "validate":
            payload = _load(args.input)
            window = payload.get("telemetry_window") if isinstance(payload, dict) else payload
            if not isinstance(window, list):
                raise TelemetryContractError("validate input must be telemetry_window[] or scenario JSON")
            validate_window(window)
            result = {"valid": True, "points": len(window)}
        else:
            raise AssertionError(args.mode)
    except (KeyError, TelemetryContractError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    _dump(result, getattr(args, "output", None))
    return 0


def _load(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _dump(data, path: str | None) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    else:
        print(text)


if __name__ == "__main__":
    raise SystemExit(main())
