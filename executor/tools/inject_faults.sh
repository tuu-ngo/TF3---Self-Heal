#!/usr/bin/env bash
# Inject fault THẬT vào podinfo (tenant-a) qua chaos endpoints + ghi ground_truth.json.
# Sinh dataset có NHÃN (inject_time + fault_type) cho AI team tune/test detect.
# Cần: loadgen deployment đang chạy (manifests/loadgen/loadgen.yaml) để có traffic nền.
#
#   AWS_REGION=us-east-1 bash executor/tools/inject_faults.sh
#
# Chuỗi ~15 phút: baseline → delay(p95) → errors(5xx) → crash(restart), mỗi pha ghi mốc.
set -u
NS=tenant-a; SVC="http://checkout-svc.tenant-a.svc.cluster.local"
OUT="data-export/ground_truth.json"
POD=$(kubectl -n $NS get pod -l app=loadgen -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
[ -z "$POD" ] && { echo "loadgen chưa chạy — apply manifests/loadgen/loadgen.yaml trước"; exit 1; }

burst() { # $1=path $2=duration_s  — drive endpoint mạnh trong pod loadgen
  kubectl -n $NS exec "$POD" -- sh -c "
    end=\$(( \$(date +%s) + $2 ))
    while [ \$(date +%s) -lt \$end ]; do
      for i in 1 2 3 4 5 6 7 8; do wget -qO- --timeout=5 \"$SVC$1\" >/dev/null 2>&1 & done
      wait; done" 2>/dev/null
}

echo "{" > "$OUT"; first=1
record() { # $1=fault $2=inject_time $3=runbook
  [ $first -eq 0 ] && echo "," >> "$OUT"; first=0
  cat >> "$OUT" <<EOF
  "cdo-sample-api_$1_1": {"service_fault":"cdo-sample-api_$1","run_id":"1","inject_time":$2,"target_service":"cdo-sample-api","suspected_fault_type":"$1","matched_runbook":"$3"}
EOF
}

echo "[inject] baseline 240s ($(date +%H:%M:%S))"; sleep 240

T=$(date +%s); echo "[inject] DELAY @ $T (180s)"; burst "/delay/2" 180; record "delay" "$T" "ServiceStuckRestartRunbook"
echo "[inject] recover 120s"; sleep 120

T=$(date +%s); echo "[inject] ERRORS(5xx) @ $T (180s)"; burst "/status/500" 180; record "loss" "$T" "ServiceStuckRestartRunbook"
echo "[inject] recover 120s"; sleep 120

T=$(date +%s); echo "[inject] CRASH(panic) @ $T"; for n in 1 2 3; do kubectl -n $NS exec "$POD" -- wget -qO- --timeout=3 "$SVC/panic" >/dev/null 2>&1; sleep 2; done
record "restart" "$T" "ServiceStuckRestartRunbook"; sleep 60

echo "}" >> "$OUT"
echo "[inject] XONG — ground_truth: $OUT"; cat "$OUT"
