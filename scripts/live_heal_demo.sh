#!/usr/bin/env bash
# =============================================================================
# LIVE self-heal demo với AI engine THẬT — pattern MEMORY SPIKE.
# ĐÃ VERIFY: detect(mem,0.95) -> PATCH_MEMORY_LIMIT -> execute success
#            -> verify DONE -> incident_closed: auto_resolved.
#
# CƠ CHẾ: engine (BOCPD) chỉ ra `mem` khi có BASELINE phẳng (>=40 điểm ~11'@15s)
# RỒI SPIKE. Mỗi lần `deploy` tạo deployment TÊN DUY NHẤT (heal-demo-<time>) để
# cửa sổ Prometheus SẠCH (không lẫn pod cũ -> tránh RCA rối -> tránh escalate).
# Container tên `podinfo` để PATCH_MEMORY khớp.
#
# QUY TRÌNH (chạy: bash scripts/live_heal_demo.sh <lệnh>):
#   1) deploy  -> LÚC SETUP (đầu buổi). Baseline tích luỹ ~11'.
#   2) status  -> chờ "Baseline đủ: YES".
#   3) demo    -> BẤM LIVE: tự spike -> chờ spike vào Prometheus -> trigger
#                 -> tail log tới khi auto_resolved. (chạy ~3-4 phút, tự chạy hết)
#   4) clean   -> dọn sau demo.
# =============================================================================
set -uo pipefail
export AWS_REGION=${AWS_REGION:-us-east-1}
NS=tenant-a
NAMEFILE=/tmp/.heal_demo_name
QURL=https://sqs.us-east-1.amazonaws.com/012619468490/cdo-telemetry-dev
TENANT=6c8b4b2b-4d45-4209-a1b4-4b532d56a31c
PROM='http://kube-prometheus-stack-prometheus.monitoring.svc.cluster.local:9090'
name() { cat "$NAMEFILE" 2>/dev/null; }

deploy() {
  DEP="heal-demo-$(date +%H%M%S)"; echo "$DEP" > "$NAMEFILE"
  cat <<YAML | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata: {name: $DEP, namespace: $NS, labels: {app: $DEP}}
spec:
  replicas: 1
  selector: {matchLabels: {app: $DEP}}
  template:
    metadata: {labels: {app: $DEP}}
    spec:
      containers:
        - name: podinfo
          image: python:3.12-slim
          # baseline 35MB phẳng (dưới limit 1024Mi, KHÔNG OOM). Khi /tmp/spike tồn tại
          # -> giữ ~635MB (vẫn < limit -> pod SỐNG, memory bậc-thang rõ). BOCPD thấy
          # baseline+spike -> anomaly=true sev 0.95. Executor (GATE_CONF_EXECUTE=0.45)
          # PROCEED -> PATCH_MEMORY(podinfo) -> verify DONE -> auto_resolved.
          command: ["python","-u","-c","import time,os\nbase=bytearray(35*1024*1024)\nprint('baseline 35MB, cho /tmp/spike',flush=True)\nsp=None\nwhile True:\n if sp is None and os.path.exists('/tmp/spike'):\n  print('SPIKE 635MB',flush=True); sp=bytearray(600*1024*1024)\n time.sleep(2)"]
          resources:
            requests: {memory: 64Mi, cpu: 50m}
            limits: {memory: 1024Mi, cpu: 200m}
          volumeMounts:
            - {name: tmp, mountPath: /tmp}
      volumes:
        - {name: tmp, emptyDir: {}}
YAML
  echo ">> Deploy '$DEP'. CHỜ ~11 phút baseline. Kiểm tra: bash $0 status"
}

points() {
  DEP=$(name)
  kubectl -n self-heal-system exec deploy/ai-engine -- python -c "
import urllib.request,urllib.parse,json,time
end=int(time.time());start=end-3600
q='container_memory_working_set_bytes{namespace=\"$NS\",pod=~\"$DEP-.*\",container!=\"\",image!=\"\"}'
u='$PROM/api/v1/query_range?query='+urllib.parse.quote(q)+'&start='+str(start)+'&end='+str(end)+'&step=15'
r=json.load(urllib.request.urlopen(u,timeout=15))['data']['result']
v=r[0]['values'] if r else []; mb=[round(float(x[1])/1e6) for x in v]
print(len(mb), mb[-1] if mb else 0, max(mb) if mb else 0)
" 2>/dev/null
}

status() {
  DEP=$(name); [ -z "$DEP" ] && { echo "Chưa deploy — chạy: bash $0 deploy"; exit 1; }
  kubectl -n $NS get pods -l app=$DEP 2>/dev/null
  read -r n last mx <<< "$(points)"
  echo "deployment=$DEP | points=${n:-0} | last=${last:-?}MB | max=${mx:-?}MB"
  if [ "${n:-0}" -ge 40 ]; then echo "Baseline đủ (>=40): YES -> sẵn sàng: bash $0 demo"
  else echo "Baseline đủ (>=40): CHUA (${n:-0}/40) -> chờ thêm ~$(( (40-${n:-0})*15/60 +1 )) phút"; fi
}

demo() {
  DEP=$(name); [ -z "$DEP" ] && { echo "Chưa deploy."; exit 1; }
  read -r n _ _ <<< "$(points)"
  [ "${n:-0}" -lt 40 ] && { echo "⚠ baseline mới ${n:-0}/40 điểm — chờ thêm rồi hãy demo (bash $0 status)."; exit 1; }
  POD=$(kubectl -n $NS get pod -l app=$DEP -o jsonpath='{.items[0].metadata.name}')
  echo ">> [1/3] SPIKE memory 635MB trên $DEP ..."
  kubectl -n $NS exec "$POD" -- python -c "open('/tmp/spike','w').close()"
  echo ">> [2/3] Chờ spike vào Prometheus (~150s)..."; sleep 150
  echo ">> [3/3] Gửi trigger + theo dõi self-heal:"
  MID=$(aws sqs send-message --queue-url "$QURL" --message-body \
"{\"ts\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"tenant_id\":\"$TENANT\",\"service\":\"$DEP\",\"signal_name\":\"container_resource_usage\",\"value\":635000000,\"labels\":{\"system\":\"K8S_NATIVE\",\"namespace\":\"$NS\",\"deployment\":\"$DEP\",\"container\":\"podinfo\"}}" \
    --query MessageId --output text)
  echo "   (SQS MessageId=$MID) — chờ executor drain ~20-40s. Ctrl-C để dừng."
  kubectl -n self-heal-system logs -f --tail=2 deploy/cdo-executor \
    | grep --line-buffered -iE "$DEP|detect_response|action_plan|safety_passed|execute_done|verify_done|incident_closed|escalat"
}

clean() { DEP=$(name); [ -n "$DEP" ] && kubectl -n $NS delete deploy "$DEP" --ignore-not-found; rm -f "$NAMEFILE"; }

case "${1:-}" in
  deploy) deploy ;;
  status) status ;;
  demo)   demo ;;
  clean)  clean ;;
  *) echo "dùng: bash $0 {deploy|status|demo|clean}"; exit 1 ;;
esac
