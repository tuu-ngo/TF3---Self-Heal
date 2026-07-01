#!/usr/bin/env bash
# Inject fault COHERENT trên Online Boutique (tenant-a) + ghi ground_truth_ob.json.
# Metric OB = cadvisor (cpu/mem/restarts) — không có app metric → fault chọn kiểu hiện ở cadvisor+log:
#   1) cpu/load: scale loadgenerator 1->4 (traffic x4) → cpu OB services tăng + log volume tăng.
#   2) restart : xoá pod checkoutservice → restart_count tăng + frontend/checkout log lỗi.
# Dataset (metric+log+nhãn) đều trên Online Boutique → khớp platform_profile_online_boutique.
set -u
NS=tenant-a
OUT="data-export/ground_truth_ob.json"

echo "{" > "$OUT"; first=1
record() { [ $first -eq 0 ] && echo "," >> "$OUT"; first=0
  cat >> "$OUT" <<EOF
  "${1}_1": {"service_fault":"$1","run_id":"1","inject_time":$2,"target_service":"$3","suspected_fault_type":"$4","matched_runbook":"$5"}
EOF
}

echo "[ob] baseline 240s ($(date +%H:%M:%S))"; sleep 240

# --- Fault 1: cpu/load spike ---
T=$(date +%s); echo "[ob] CPU/LOAD @ $T — loadgenerator 1->4 (180s)"
kubectl -n $NS scale deploy/loadgenerator --replicas=4 >/dev/null 2>&1
sleep 180
record "frontend_cpu" "$T" "frontend" "cpu" "ServiceStuckRestartRunbook"
kubectl -n $NS scale deploy/loadgenerator --replicas=1 >/dev/null 2>&1
echo "[ob] recover 120s"; sleep 120

# --- Fault 2: crash/restart checkoutservice ---
T=$(date +%s); echo "[ob] CRASH checkoutservice @ $T"
for n in 1 2 3; do kubectl -n $NS delete pod -l app=checkoutservice --grace-period=0 --force >/dev/null 2>&1; sleep 25; done
record "checkoutservice_restart" "$T" "checkoutservice" "restart" "ServiceStuckRestartRunbook"
sleep 60

echo "}" >> "$OUT"
echo "[ob] XONG — ground_truth: $OUT"; cat "$OUT"
