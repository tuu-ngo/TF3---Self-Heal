"""Demo AI smoke test — bản Online Boutique (detect->decide->verify) trên engine LIVE.
Khác demo_ai_smoke.py ở chỗ target service OB (container 'server', không phải 'podinfo').
Chọn service qua env SVC (mặc định emailservice).

  Git Bash:   SVC=emailservice kubectl -n self-heal-system exec -i deploy/ai-engine -- python - < scripts/demo_ai_smoke_ob.py
  PowerShell: Get-Content scripts/demo_ai_smoke_ob.py | kubectl -n self-heal-system exec -i deploy/ai-engine -- python -

LƯU Ý: env SVC được đọc TRONG pod (không phải máy local). Muốn đổi service khi chạy
qua stdin, sửa DEFAULT_SVC bên dưới, hoặc set trong pod. Mặc định emailservice là đủ demo.
"""
import os, urllib.request, urllib.error, json, uuid, datetime, time

DEFAULT_SVC = "emailservice"
SVC = os.environ.get("SVC", DEFAULT_SVC)
CONTAINER = "server"  # container name chuẩn của Online Boutique
BASE = "http://127.0.0.1:8080"
TENANT = str(uuid.uuid4())


def post(path, payload):
    idem, corr = str(uuid.uuid4()), str(uuid.uuid4())
    payload = dict(payload, idempotency_key=idem, correlation_id=corr, dry_run_mode=True)
    hdr = {"Content-Type": "application/json", "X-Tenant-Id": TENANT,
           "Idempotency-Key": idem, "X-Dry-Run-Mode": "true", "X-Correlation-Id": corr}
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(), headers=hdr)
    t0 = time.time()
    try:
        r = urllib.request.urlopen(req, timeout=60)
        return r.status, json.loads(r.read()), round(time.time() - t0, 2)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300], round(time.time() - t0, 2)


now = datetime.datetime.now(datetime.timezone.utc)
print(f"# target Online Boutique service = {SVC} (container={CONTAINER})")
pts = [{
    "ts": (now - datetime.timedelta(seconds=(180 - i) * 15)).isoformat().replace("+00:00", "Z"),
    "tenant_id": TENANT, "service": SVC, "signal_name": "container_resource_usage",
    "value": (30e6 + (i % 5) * 2e6 if i < 120 else 30e6 + (i - 120) * 8e6),
    "labels": {"system": "K8S_NATIVE", "namespace": "tenant-a",
               "deployment": SVC, "container": CONTAINER},
} for i in range(180)]

st, b, dt = post("/v1/detect", {"telemetry_window": pts})
if not isinstance(b, dict):
    print(f"[DETECT] HTTP {st} in {dt}s -> ERROR: {b}"); raise SystemExit(1)
ctx = b.get("anomaly_context", {})
print(f"[DETECT] {st} {dt}s -> anomaly={b.get('anomaly_detected')} "
      f"severity={b.get('severity')} fault={ctx.get('suspected_fault_type')} "
      f"deployment={ctx.get('deployment')}")

st2, b2, _ = post("/v1/decide", {"anomaly_context": ctx})
if isinstance(b2, dict) and b2.get("action_plan"):
    ap = b2["action_plan"][0]
    cont = ap.get("params", {}).get("container")
    print(f"[DECIDE] {st2} -> runbook={b2.get('matched_runbook')} action={ap['action']} "
          f"container={cont} type={b2.get('pattern_type')}")
    if ap["action"] == "PATCH_MEMORY_LIMIT" and cont != CONTAINER:
        print(f"  ⚠ action nhắm container '{cont}' != '{CONTAINER}' của OB → "
              f"trên cluster Kyverno #4 sẽ CHẶN (fail-safe). Dùng fault non-mem để ra RESTART. Xem docs/12 §0.")
else:
    print(f"[DECIDE] {st2} -> {b2}")


def win(err):
    return [{"ts": now.isoformat().replace("+00:00", "Z"), "tenant_id": TENANT,
             "service": SVC, "signal_name": "service_error_rate", "value": err,
             "labels": {"system": "K8S_NATIVE", "namespace": "tenant-a", "deployment": SVC}}
            for _ in range(60)]


act = {"action": "RESTART_DEPLOYMENT", "target": f"deployment/{SVC}",
       "status": "COMPLETED", "execution_time_seconds": 5}
for name, err in [("hoi phuc err=0.0", 0.0), ("con loi err=0.5", 0.5)]:
    stv, bv, _ = post("/v1/verify", {"action_executed": act, "post_telemetry_window": win(err)})
    if isinstance(bv, dict):
        print(f"[VERIFY {name}] {stv} -> success={bv.get('success')} next_action={bv.get('next_action')}")
    else:
        print(f"[VERIFY {name}] {stv} -> {bv}")
