#!/usr/bin/env bash
# =============================================================================
# LIVE self-heal demo với AI engine THẬT — pattern dễ nhất: MEMORY SPIKE.
# ĐÃ VERIFY 2026-07-02: detect(mem,0.95) -> PATCH_MEMORY_LIMIT -> execute success
#                       -> verify DONE -> incident_closed: auto_resolved.
#
# CƠ CHẾ: engine (BOCPD) chỉ ra `mem` khi có BASELINE phẳng (>=40 điểm ~10' @15s)
# RỒI SPIKE. Deployment `mem-demo` (container `podinfo` để PATCH khớp) giữ 35MB
# phẳng, CHỜ file /tmp/spike; khi bạn `spike` -> nhảy 635MB -> watcher/detect bắt
# -> PATCH_MEMORY(podinfo) -> verify DONE -> auto_resolved.
#
# QUY TRÌNH DEMO (chạy bằng: bash scripts/live_heal_demo.sh <lệnh>):
#   1) deploy   -> LÚC SETUP (đầu buổi). Baseline bắt đầu tích luỹ.
#   2) status   -> chờ tới khi "Baseline đủ (>=40 điểm): YES" (~10-11 phút).
#   3) spike    -> BẤM khi tới lượt demo: memory nhảy 635MB.
#   4) watch    -> xem self-heal chạy live (watcher tự heal trong ~30-90s).
#                  (KHÔNG cần bước này nếu chỉ muốn xem; watcher tự làm.)
#   5) clean    -> dọn sau demo.
# LƯU Ý: sau khi heal xong có cooldown 5' — đừng spike/trigger lại ngay.
# =============================================================================
set -euo pipefail
export AWS_REGION=${AWS_REGION:-us-east-1}
NS=tenant-a; DEP=mem-demo
PROM='http://kube-prometheus-stack-prometheus.monitoring.svc.cluster.local:9090'

deploy() {
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
        - name: podinfo               # tên khớp PATCH_MEMORY (profile CDO)
          image: python:3.12-slim
          command: ["python","-u","-c","import time,os\nbase=bytearray(35*1024*1024)\nprint('baseline 35MB — chờ /tmp/spike',flush=True)\nsp=None\nwhile True:\n if sp is None and os.path.exists('/tmp/spike'):\n  sp=bytearray(600*1024*1024); print('SPIKED 635MB',flush=True)\n time.sleep(3)"]
          resources:
            requests: {memory: 64Mi, cpu: 50m}
            limits: {memory: 1024Mi, cpu: 200m}
YAML
  echo ">> Deploy xong. CHỜ ~10-11 phút cho baseline (dùng: bash $0 status)."
}

status() {
  kubectl -n $NS get pods -l app=$DEP 2>/dev/null || true
  kubectl -n self-heal-system exec deploy/ai-engine -- python -c "
import urllib.request,urllib.parse,json,time
end=int(time.time());start=end-3600
q='container_memory_working_set_bytes{namespace=\"$NS\",pod=~\"$DEP-.*\",container!=\"\",image!=\"\"}'
u='$PROM/api/v1/query_range?query='+urllib.parse.quote(q)+'&start='+str(start)+'&end='+str(end)+'&step=15'
r=json.load(urllib.request.urlopen(u,timeout=15))['data']['result']
v=r[0]['values'] if r else []; mb=[round(float(x[1])/1e6) for x in v]
print('points=',len(mb),'| last=',mb[-1] if mb else '-','MB | max=',max(mb) if mb else '-','MB')
print('Baseline đủ (>=40 điểm):','YES -> có thể spike' if len(mb)>=40 else 'CHUA -> chờ thêm')
print('Đã spike (data >300MB):','YES' if (mb and max(mb)>300) else 'chưa')
"
}

spike() {
  POD=$(kubectl -n $NS get pod -l app=$DEP -o jsonpath='{.items[0].metadata.name}')
  [ -z "$POD" ] && { echo "Chưa có pod $DEP — chạy deploy trước."; exit 1; }
  kubectl -n $NS exec "$POD" -- python -c "open('/tmp/spike','w').close()"
  echo ">> ĐÃ SPIKE. Memory nhảy 635MB. Xem self-heal: bash $0 watch"
}

watch() {
  echo ">> Theo dõi executor (Ctrl-C để dừng). Watcher sẽ bắt trong ~30-90s:"
  kubectl -n self-heal-system logs -f --tail=3 deploy/cdo-executor \
    | grep --line-buffered -iE "$DEP|prom_window_built|detect_response|action_plan|safety_passed|execute_done|verify_done|incident_closed|escalat"
}

clean() { kubectl -n $NS delete deploy $DEP --ignore-not-found; }

case "${1:-}" in
  deploy) deploy ;;
  status) status ;;
  spike)  spike ;;
  watch)  watch ;;
  clean)  clean ;;
  *) echo "dùng: bash $0 {deploy|status|spike|watch|clean}"; exit 1 ;;
esac
