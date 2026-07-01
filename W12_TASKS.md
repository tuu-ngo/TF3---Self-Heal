# PLAYBOOK CÔNG VIỆC TUẦN W12 — CDO-02 (cầm tay chỉ việc)

**Tuần build:** T2 29/06 → T5 02/07/2026 · **🛑 Code freeze: 8h sáng T5 02/07**
**Đọc kèm:** [Role.md](Role.md) · [WORK_RULE.md](WORK_RULE.md) · [executor/README.md](executor/README.md)

> Mỗi task = 1 Jira card. Mỗi task có **4 phần**: 🎯 Mục tiêu · 🔧 Các bước · ✅ Kiểm tra · 📎 Evidence (đính khi close).
> Ưu tiên: **MUST** (không có = fail) · **SHOULD** (làm nếu MUST xong) · **CUT** (bỏ trước nếu trễ).
> Quy ước env executor (xem [config.py](executor/config.py)): `CDO_K8S_MOCK=true` = chạy giả lập (chưa cần cluster); bỏ đi = chạy thật.

## Mốc cố định (cả team — đừng quên)
| Khi | Sự kiện | Ai lo |
|---|---|---|
| Mỗi ngày 14h | Standup 15' → ghi `docs/standup_notes.md` | tất cả |
| T2 16h | Curveball #2 (medium, 30') → ghi `curveball-responses.md` | C3 dẫn, cả team |
| T3 14–16h | Integration: gọi **AI engine THẬT** (hết mock) | A4 + B3 |
| T4 14h | Curveball #3 (chaos, 60') → ghi response; tối dry-run | C3 dẫn |
| **T5 8h** | **FREEZE** + `git tag final && git push --tags` | A1 |
| T5 13h30 | Buổi chấm TF3 | tất cả |

---
---

# 🟦 SUBTEAM A — SELF-HEAL CORE (executor/)

**Bối cảnh:** Skeleton đã chạy được với mock (`auto_resolved`). Việc tuần này là **thay stub bằng code thật**: gọi K8s thật, ghi audit S3 thật, lock DynamoDB thật, tích hợp AI thật. Mỗi người làm trên nhánh riêng `executor/<việc>`, PR cho A1 review.

> Trước khi bắt đầu, mỗi người chạy thử 1 lần để hiểu luồng:
> ```bash
> cd executor
> python mock_ai_server.py &                 # cửa sổ 1
> CDO_K8S_MOCK=true AI_BASE_URL=http://127.0.0.1:8080 python main.py scenarios/tc01_service_stuck.json
> python tests/test_safety_gate.py
> ```

---

### A-01 — Chốt SA namespace với AI team · **MUST** · A1 · T2 sáng
🎯 Contract §3.D bắt ServiceAccount `tf3-cdo-controller` nằm ở `self-heal-system`, nhưng design cũ để executor ở `platform`. Phải chốt 1 chỗ, nếu không manifest apply sẽ sai RBAC.
🔧 Các bước:
1. Nhắn AI team (theo mẫu): *"CDO-02 sẽ đặt executor SA `tf3-cdo-controller` trong `self-heal-system` đúng contract §3.D. Xác nhận giúp."*
2. Nếu đồng ý → giữ default `CDO_EXECUTOR_NS=self-heal-system` (đã set sẵn trong [config.py](executor/config.py)).
3. Nếu muốn giữ `platform` → phải có câu trả lời **bằng văn bản** (screenshot chat) và set `CDO_EXECUTOR_NS=platform`.
4. Báo B1 để RBAC RoleBinding (task B-11) trỏ đúng namespace.
✅ Kiểm tra: có 1 câu trả lời rõ ràng từ AI team; biến `CDO_EXECUTOR_NS` đã chốt.
📎 Evidence: screenshot xác nhận + commit sửa `config.py` (nếu đổi).

---

### A-02 — `k8s_client.get_deployment_state` thật (cho snapshot) · **MUST** · A3 · T2
🎯 Trước khi execute, CDO phải đọc state hiện tại của deployment để rollback được (contract-new-4: AI không trả `rollback_snapshot`).
🔧 Các bước:
1. Cài lib: trong [executor/requirements.txt](executor/requirements.txt) bỏ comment `kubernetes>=29.0`, rồi `pip install -r requirements.txt`.
2. Mở [executor/k8s_client.py](executor/k8s_client.py), thay thân hàm `get_deployment_state` (đang trả `{"_mock": True}`) bằng code thật:
   ```python
   def get_deployment_state(self, namespace: str, name: str) -> dict:
       if not self.enabled:                      # mock mode
           return {"_mock": True, "namespace": namespace, "name": name}
       dep = self.apps.read_namespaced_deployment(name, namespace)
       c = dep.spec.template.spec.containers[0]
       limits = (c.resources.limits or {}) if c.resources else {}
       return {
           "replica_count": dep.spec.replicas,
           "image_tag": c.image,
           "memory_limit": limits.get("memory"),
           "revision": dep.metadata.annotations.get(
               "deployment.kubernetes.io/revision"),
       }
   ```
3. Test trên cluster (sau khi B-01 xong): `aws eks update-kubeconfig --name cdo-eks-cluster-dev --region us-east-1` để có kubeconfig.
✅ Kiểm tra:
   ```bash
   cd executor
   python -c "from k8s_client import K8sClient; print(K8sClient(in_cluster=False).get_deployment_state('tenant-a','cdo-sample-api'))"
   # phải in ra replica_count/image_tag thật, không có _mock
   ```
📎 Evidence: output lệnh trên (dán vào Jira).

---

### A-03 — `RESTART_DEPLOYMENT` thật + server-side dry-run · **MUST** · A3 · T2–T3
🎯 Action quan trọng nhất, đã chứng minh tay ở W11 — giờ để executor tự làm, có dry-run trước.
🔧 Các bước:
1. Trong [k8s_client.py](executor/k8s_client.py) thay hàm `restart_deployment` (đang gọi `_stub`):
   ```python
   from datetime import datetime, timezone
   def restart_deployment(self, namespace, name, dry_run=False):
       if not self.enabled:
           return self._stub("RESTART_DEPLOYMENT", namespace, name, dry_run)
       body = {"spec": {"template": {"metadata": {"annotations": {
           "kubectl.kubernetes.io/restartedAt":
               datetime.now(timezone.utc).isoformat()}}}}}
       kwargs = {"dry_run": "All"} if dry_run else {}   # server-side dry-run
       self.apps.patch_namespaced_deployment(name, namespace, body, **kwargs)
       return {"status": "OK", "action": "RESTART_DEPLOYMENT",
               "namespace": namespace, "name": name, "dry_run": dry_run}
   ```
2. Logic dry-run→execute đã có sẵn trong [executors/urgent.py](executor/executors/urgent.py) (`_dispatch(dry_run=True)` trước, fail thì không execute). Không phải sửa.
3. Chạy E2E thật (cần B-01, B-03 xong + AI mock hoặc thật):
   ```bash
   cd executor
   AI_BASE_URL=http://127.0.0.1:8080 python main.py scenarios/tc01_service_stuck.json
   # KHÔNG set CDO_K8S_MOCK → gọi cluster thật
   ```
✅ Kiểm tra: `kubectl get pods -n tenant-a` thấy pod `cdo-sample-api` bị thay (tên đổi, AGE reset); log executor có `execute_done result=success`.
📎 Evidence: log JSON `execute_done` + `kubectl rollout status deployment/cdo-sample-api -n tenant-a`.

---

### A-04 — `PATCH_MEMORY_LIMIT` thật · **MUST** · A3 · T3
🎯 Pattern OOM (TC-04): đổi memory limit của container.
🔧 Trong [k8s_client.py](executor/k8s_client.py) thay `patch_memory_limit`:
   ```python
   def patch_memory_limit(self, namespace, name, container,
                          request_mb, limit_mb, dry_run=False):
       if not self.enabled:
           return self._stub("PATCH_MEMORY_LIMIT", namespace, name, dry_run,
                             container=container)
       res = {"limits": {"memory": f"{limit_mb}Mi"}}
       if request_mb:
           res["requests"] = {"memory": f"{request_mb}Mi"}
       body = {"spec": {"template": {"spec": {"containers":
               [{"name": container, "resources": res}]}}}}
       kwargs = {"dry_run": "All"} if dry_run else {}
       self.apps.patch_namespaced_deployment(name, namespace, body, **kwargs)
       return {"status": "OK", "action": "PATCH_MEMORY_LIMIT",
               "namespace": namespace, "name": name, "dry_run": dry_run}
   ```
✅ Kiểm tra: tạo scenario OOM (xem C-02), chạy → `kubectl get deployment cdo-sample-api -n tenant-a -o jsonpath='{.spec.template.spec.containers[0].resources.limits.memory}'` trả giá trị mới. **Lưu ý**: limit phải ≤ 4Gi nếu không Kyverno (B-06) chặn — đúng ý đồ.
📎 Evidence: giá trị memory trước/sau + log execute.

---

### A-05 — `ROLLOUT_UNDO` (rollback urgent) · **SHOULD** · A3 · T3
🎯 Khi `/v1/verify` trả `next_action=ROLLBACK` (TC-14), hoàn tác về bản trước.
🔧 Cách nhanh & chắc cho capstone (dùng kubectl qua subprocess):
   ```python
   import subprocess
   def rollout_undo(self, namespace, name, dry_run=False):
       if not self.enabled or dry_run:
           return self._stub("ROLLOUT_UNDO", namespace, name, dry_run)
       subprocess.run(["kubectl", "rollout", "undo",
                       f"deployment/{name}", "-n", namespace], check=True)
       return {"status": "OK", "action": "ROLLOUT_UNDO",
               "namespace": namespace, "name": name}
   ```
✅ Kiểm tra: chạy TC-14 (verify trả ROLLBACK) → `kubectl rollout history deployment/cdo-sample-api -n tenant-a` thấy revision lùi.
📎 Evidence: rollout history + log `rollback_done`.

---

### A-06 — Idempotency DynamoDB thật · **MUST** · A2 · T2–T3
🎯 Chặn execute trùng cùng `Idempotency-Key` (TC-11). Logic conditional write đã code sẵn.
🔧 Các bước:
1. Bỏ comment `boto3>=1.34` trong [requirements.txt](executor/requirements.txt), `pip install -r requirements.txt`.
2. [idempotency.py](executor/idempotency.py) đã dùng `boto3` + `ConditionExpression="attribute_not_exists(idempotency_key)"` — **không phải sửa code**, chỉ cần bật AWS mode.
3. Bật AWS thật bằng cách set 2 env (lấy tên table từ B-03):
   ```bash
   export CDO_IDEMPOTENCY_TABLE=cdo-idempotency-dev
   export CDO_AUDIT_BUCKET=cdo-audit-cdo-eks-cluster-dev-dev   # cờ "đang chạy AWS"
   export AWS_REGION=us-east-1
   ```
   *(Lưu ý: code dùng `cfg.audit_bucket` khác rỗng làm cờ bật DynamoDB thật — xem [idempotency.py](executor/idempotency.py) dòng `if _HAS_BOTO and cfg.audit_bucket`.)*
✅ Kiểm tra: chạy cùng 1 scenario 2 lần với cùng idempotency_key → lần 2 audit ghi `idempotency_duplicate_denied`, không execute lại. Hoặc `aws dynamodb scan --table-name cdo-idempotency-dev` thấy item.
📎 Evidence: 2 log run + dynamodb scan output.

---

### A-07 — Audit writer → S3 Object Lock thật · **MUST** · A4 · T3
🎯 Mỗi incident ghi 1 object bất biến vào S3 (Governance 90 ngày), query theo `correlation_id`.
🔧 Các bước:
1. `boto3` đã cài (A-06). [audit.py](executor/audit.py) đã code `s3.put_object` — không phải sửa.
2. Set `CDO_AUDIT_BUCKET` = tên bucket từ B-03 (xem trên). Khi bucket khác rỗng, `AuditLogger.flush()` tự ghi S3.
3. Chạy 1 incident thật.
✅ Kiểm tra:
   ```bash
   aws s3 ls s3://cdo-audit-cdo-eks-cluster-dev-dev/audit/6c8b4b2b-4d45-4209-a1b4-4b532d56a31c/
   aws s3 cp s3://.../audit/<tenant>/<correlation_id>.json - | python -m json.tool
   # phải thấy đủ chuỗi event: alert_received ... incident_closed
   ```
📎 Evidence: object key + nội dung JSON audit 1 incident.

---

### A-08 — Tích hợp AI engine THẬT (bỏ mock) · **MUST** · A4 · T3 (integration session)
🎯 Đến 14h T3 phải gọi engine thật của AI team trên cluster mình, không dùng `mock_ai_server.py` nữa.
🔧 Các bước:
1. Chờ B-10 deploy xong AI pod trong `self-heal-system`.
2. Trỏ executor sang service nội bộ (đã là default trong config):
   ```bash
   unset AI_BASE_URL   # dùng default http://ai-engine.self-heal-system.svc.cluster.local:8080
   ```
   (Nếu chạy executor ngoài cluster để test: `kubectl port-forward -n self-heal-system svc/ai-engine 8080:8080` rồi `AI_BASE_URL=http://127.0.0.1:8080`.)
3. Chạy 1 scenario, đối chiếu response thật có đúng schema không (so với `models.py`).
4. Nếu AI trả field lạ/thiếu → báo AI team ngay (đây chính là mục đích integration session).
✅ Kiểm tra: E2E qua AI thật ra `auto_resolved`, không lỗi parse schema.
📎 Evidence: log run qua endpoint thật (không phải 127.0.0.1 mock) + correlation_id.

---

### A-09 — Unit test `pre_decide_gate` + nâng coverage · **MUST** · A2 · T3
🎯 CI cổng 2 yêu cầu coverage ≥70%; hiện chỉ `safety_gate` được test.
🔧 Tạo `executor/tests/test_pre_decide_gate.py` theo mẫu test có sẵn:
   ```python
   import sys; from pathlib import Path
   sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
   from pre_decide_gate import evaluate, FlapTracker, PROCEED, NO_ANOMALY  # noqa: E402
   from models import DetectResponse  # noqa: E402

   def _d(anom=True, conf=0.9, sev=0.8):
       return DetectResponse(anom, sev, conf, "r", "cid")

   def test_no_anomaly():
       assert evaluate(_d(anom=False), FlapTracker()).decision == NO_ANOMALY
   def test_low_conf_discard():
       assert not evaluate(_d(conf=0.3), FlapTracker()).proceed
   def test_high_conf_proceeds():
       assert evaluate(_d(conf=0.9, sev=0.8), FlapTracker()).decision == PROCEED
   def test_mid_conf_high_sev_escalates():
       assert evaluate(_d(conf=0.65, sev=0.9), FlapTracker()).escalate
   ```
2. Mở rộng cờ coverage trong [.github/workflows/ci.yml](.github/workflows/ci.yml): `--cov=safety_gate --cov=pre_decide_gate`.
✅ Kiểm tra: `cd executor && python -m pytest -q --cov=safety_gate --cov=pre_decide_gate --cov-fail-under=70` xanh.
📎 Evidence: output pytest coverage.

---

### A-10 — Test error policy `ai_client` · **SHOULD** · A4 · T3
🎯 Chứng minh 429 backoff / 500 retry×2 / 503 escalate đúng contract §4.
🔧 Viết `tests/test_ai_client.py` dùng `responses` hoặc monkeypatch `requests` để giả mã lỗi, assert: 503→`AIUnavailable`, 500→retry 2 lần rồi `AIInternalError`, 409→`AIConflict`.
✅ Kiểm tra: pytest pass.
📎 Evidence: output pytest.

---

### A-11 — Escalation thật (Slack/mock pager) · **SHOULD** · A4 · T4
🎯 Khi escalate (TC-12), gửi `escalation_bundle` ra kênh cảnh báo.
🔧 Trong [main.py](executor/main.py) hàm `_escalate`, thêm 1 lệnh POST Slack webhook:
   ```python
   import os, requests
   hook = os.environ.get("CDO_SLACK_WEBHOOK")
   if hook:
       requests.post(hook, json={"text": f"[CDO-02] escalate {reason} cid={self...}"})
   ```
   (Nếu không có webhook → in stdout là đủ cho demo.)
✅ Kiểm tra: chạy TC-12 (force AI 503) → có message ra Slack/stdout + audit `escalated`.
📎 Evidence: screenshot Slack hoặc log escalate.

---

### A-12 — Circuit breaker · **CUT** · A2 · T4
🎯 ≥3 fail/1h cho 1 service → mở breaker, chặn auto-heal (TC-15).
🔧 Dùng DynamoDB đếm fail theo key `service`; nếu count ≥3 trong 1h → ghi `CIRCUIT_BREAKER_OPEN`, skip execute. (Nếu trễ → để designed-only, mô tả trong doc.)
✅ Kiểm tra: ép 3 fail liên tiếp → action thứ 4 bị chặn.
📎 Evidence: log breaker open.

---

### A-13 — Multi-step action_plan loop · **CUT** · A1 · T4
🎯 Hiện MVP chỉ chạy `action_plan[0]`. Mở rộng chạy tuần tự nhiều step.
🔧 Trong [executors/urgent.py](executor/executors/urgent.py), đổi `item = decide.action_plan[0]` thành vòng `for item in decide.action_plan:` (dừng nếu 1 step FAILED).
✅ Kiểm tra: plan 2 step chạy đủ.
📎 Evidence: log 2 execute_done.

---

### A-14 — E2E đầy đủ trên EKS thật · **MUST** · A1+A3 · T3–T4
🎯 Gộp A-03/06/07/08: 1 incident chạy hết vòng trên cluster thật, audit vào S3.
🔧 Chạy `scenarios/tc01_service_stuck.json` không mock, với đủ env AWS. Theo dõi log 12 event.
✅ Kiểm tra: OUTCOME `auto_resolved`; object audit có trên S3; pod đã restart thật.
📎 Evidence: log đầy đủ + S3 object + kubectl pods. **Đây là demo lõi — quay video luôn cho C-13.**

---

### A-15 — Review + cut-scope (vai Lead) · **MUST** · A1 · hằng ngày
🎯 Gác chất lượng + tiến độ.
🔧 Mỗi ngày: review PR theo thứ tự `executor/` > infra EKS/audit > manifests > test > docs; bấm Squash-Merge khi đủ 2 approval + CI xanh; nếu trễ → quyết cắt theo thứ tự CUT.
✅ Kiểm tra: cuối ngày không PR nào kẹt >12h; branch `main` luôn xanh.
📎 Evidence: danh sách PR merged/ngày.

---
---

# 🟩 SUBTEAM B — PLATFORM & INFRASTRUCTURE (infra/, manifests/)

**Bối cảnh:** Terraform module + manifests đã có khung; EKS từng ACTIVE ở W11. Việc tuần này là **dựng lại cluster, apply đủ infra, cung cấp ARN/endpoint cho team A**, và cài ArgoCD+Kyverno. Quy tắc state: 1 người apply 1 lúc (WORK_RULE §IV).

> Chuẩn bị: `aws configure` (account 012619468490, region us-east-1) có quyền admin/poweruser.

---

### B-01 — EKS cluster + node group ACTIVE · **MUST** · B1 · T2 sáng
🎯 Không có cluster thì A/C không chạy thật được. Đây là task chặn lớn nhất → làm đầu tiên.
🔧 Các bước:
   ```bash
   cd infra/envs/dev
   terraform init
   terraform plan -out tf.plan          # review kỹ trước khi apply
   terraform apply tf.plan              # tạo VPC + EKS + node group
   aws eks update-kubeconfig --name cdo-eks-cluster-dev --region us-east-1
   kubectl get nodes                    # phải Ready
   ```
2. Nếu node group chưa lên: kiểm tra `desired_size>=1` trong module eks.
3. Áp namespaces: `kubectl apply -f manifests/namespaces/`
✅ Kiểm tra: `kubectl get nodes` Ready; `kubectl get ns` thấy `platform tenant-a tenant-b self-heal-system argocd kyverno`.
📎 Evidence: output 2 lệnh trên.

---

### B-02 — IRSA roles (executor + ai-engine) · **MUST** · B1 · T2
🎯 Pod gọi AWS (S3/DynamoDB/Bedrock) qua IAM role, không dùng static key.
🔧 Các bước:
1. `terraform apply` module `iam/` (đã trong envs/dev). Lấy role ARN: `terraform output`.
2. Annotate ServiceAccount:
   ```bash
   kubectl annotate sa tf3-cdo-controller -n self-heal-system \
     eks.amazonaws.com/role-arn=arn:aws:iam::012619468490:role/<executor-irsa> --overwrite
   ```
✅ Kiểm tra: chạy 1 pod test trong namespace đó, `aws sts get-caller-identity` trong pod trả về role IRSA (không phải node role).
📎 Evidence: output get-caller-identity từ trong pod.

---

### B-03 — Apply audit infra + giao ARN · **MUST** · B2 · T2
🎯 Tạo S3 (Governance), DynamoDB, SQS+DLQ cho team A. Đây là task chặn A-06/A-07.
🔧 Các bước:
   ```bash
   cd infra/envs/dev
   terraform apply -target=module.audit
   terraform output            # lấy bucket name, table name, queue url
   ```
2. Nhắn team A (A2/A4) 3 giá trị: `CDO_AUDIT_BUCKET`, `CDO_IDEMPOTENCY_TABLE`, queue URL.
3. Xác nhận S3 đúng Governance: `aws s3api get-object-lock-configuration --bucket <bucket>` → `Mode: GOVERNANCE, Days: 90`.
✅ Kiểm tra: 3 tài nguyên tồn tại; object lock = GOVERNANCE 90.
📎 Evidence: terraform output + get-object-lock-configuration.

---

### B-04 — Observability (CloudWatch) · **SHOULD** · B2 · T3
🎯 Log group + alarm (executor error, Kyverno deny, DLQ rate).
🔧 `terraform apply -target=module.observability`; tạo metric filter cho log group executor.
✅ Kiểm tra: alarm hiện trên CloudWatch console.
📎 Evidence: screenshot alarm.

---

### B-05 — Cài ArgoCD + AppProject/Application · **MUST** · B3 · T2
🎯 GitOps engine cho deferred path + quản manifest.
🔧 Các bước:
   ```bash
   helm repo add argo https://argoproj.github.io/argo-helm
   helm install argocd argo/argo-cd -n argocd --create-namespace
   kubectl apply -f manifests/argocd/        # appproject + application tenant-a/b
   ```
✅ Kiểm tra: `kubectl get applications -n argocd` thấy `self-heal-tenant-a`, `self-heal-tenant-b`.
📎 Evidence: output get applications + screenshot ArgoCD UI (port-forward).

---

### B-06 — Cài Kyverno + 3 policy (dry-run→Enforce) · **MUST** · B3 · T2–T3
🎯 Lớp 3 chặn value xấu (replicas>10, memory>4Gi, namespace ngoài allowlist).
🔧 Các bước:
   ```bash
   helm repo add kyverno https://kyverno.github.io/kyverno/
   helm install kyverno kyverno/kyverno -n kyverno --create-namespace \
     --set admissionController.replicas=1
   # B1: test ở chế độ Audit trước
   kubectl apply -f manifests/kyverno/policies/
   ```
2. Test dry-run: thử `kubectl scale deployment cdo-sample-api -n tenant-a --replicas=50` → phải bị **chặn**.
✅ Kiểm tra: scale 50 bị deny với message Kyverno; scale 5 thì OK.
📎 Evidence: output lệnh scale bị deny.

---

### B-07 — NetworkPolicy allow-executor-to-ai · **MUST** · B3 · T2
🎯 Chỉ pod executor (label `app=cdo-self-heal-controller`) reach được AI port 8080.
🔧 `kubectl apply -f manifests/networkpolicies/allow-executor-to-ai.yaml`
✅ Kiểm tra: pod KHÔNG có label → `curl ai-engine:8080` timeout; pod có label → OK.
📎 Evidence: 2 kết quả curl.

---

### B-08 — Sync waves + selfHeal/prune đúng bảng · **MUST** · B3 · T3
🎯 Tránh ArgoCD revert urgent patch (vòng lặp vô tận).
🔧 Trong Application manifest: tenant-a/b/platform để `selfHeal: false, prune: false`; argocd/self-heal-system `selfHeal: true`. Gắn annotation `argocd.argoproj.io/sync-wave` 0→4 theo [04_deployment_design §3.8](docs/04_deployment_design.md).
✅ Kiểm tra: patch tay 1 deployment tenant-a → ArgoCD KHÔNG revert.
📎 Evidence: ArgoCD app diff sau patch (OutOfSync nhưng không tự sync).

---

### B-09 — Deferred path (Git→ArgoCD) · **SHOULD** · B3 · T3
🎯 Cho SCALE_REPLICAS/ROTATE_SECRET đi qua Git commit. **Nếu trễ → báo A1 hạ designed-only.**
🔧 Tạo repo/thư mục manifest `tf3-self-heal-manifests/manifests/<tenant>/`, ArgoCD watch; cấp GitHub App token cho executor push.
✅ Kiểm tra: commit đổi replicas → ArgoCD sync → deployment scale.
📎 Evidence: commit hash + ArgoCD sync event.

---

### B-10 — Deploy AI Engine wrapper (khi có image) · **MUST** · B3+A4 · khi nhận image
🎯 Deploy image AI team bàn giao vào `self-heal-system`. **Không viết nội dung AI** — chỉ wrapper.
🔧 Dùng spec sẵn trong [04_deployment_design §8](docs/04_deployment_design.md): Deployment (image ECR/registry AI), resources 500m/1Gi–1000m/2Gi, HPA 2–10, probe `/health` `/ready`, label `app: ai-engine`, IRSA cho Bedrock.
   ```bash
   kubectl apply -f manifests/ai-engine/      # tạo mới theo spec
   kubectl rollout status deployment/ai-engine -n self-heal-system
   ```
✅ Kiểm tra: AI pod Running; `kubectl exec ... curl localhost:8080/ready` → ready.
📎 Evidence: get pods + /ready output.

---

### B-11 — RBAC Role/RoleBinding per tenant · **MUST** · B1 · T2
🎯 Executor chỉ patch được deployment trong tenant namespace, cấm delete/cluster-wide.
🔧 Áp RBAC theo [deployment-contract §3.D](contract%20-%20new%204/deployment-contract.md): Role `tf3-cdo-executor-role` (get/list/patch deployments,pods,replicasets; get/create/delete secrets) + RoleBinding cho mỗi namespace tenant-a, tenant-b.
✅ Kiểm tra:
   ```bash
   kubectl auth can-i delete deployment -n tenant-a --as=system:serviceaccount:self-heal-system:tf3-cdo-controller
   # phải trả "no"
   kubectl auth can-i patch deployment -n tenant-a --as=...   # "yes"
   ```
📎 Evidence: 2 output can-i.

---

### B-12 — Đo cost thật · **MUST** · B2 · T4
🎯 `05_cost_analysis.md` phải có số measured, không estimate.
🔧 `aws ce get-cost-and-usage` cho khoảng W12, tách theo service (EKS, S3, DynamoDB, CloudWatch). Điền bảng trong [docs/05_cost_analysis.md](docs/05_cost_analysis.md).
✅ Kiểm tra: bảng có $ thật từng service.
📎 Evidence: cost explorer output.

---

### B-13 — Terraform fmt/validate + tfsec CRITICAL=0 · **MUST** · B1+B2 · ongoing
🔧 Trước mỗi PR infra: `terraform fmt -recursive`, `terraform validate`. CI job `tfsec` phải xanh (chỉ fail CRITICAL).
✅ Kiểm tra: CI gate tfsec xanh trên PR.
📎 Evidence: link CI run.

---

### B-14 — Smoke test infra · **MUST** · B1 · T3
🔧 Chạy checklist: 3 namespace OK; RBAC deny cross-tenant (B-11); ArgoCD/Kyverno Ready; NetworkPolicy chặn đúng; bucket/table tồn tại.
✅ Kiểm tra: tất cả mục pass.
📎 Evidence: checklist có tick + screenshot.

---
---

# 🟨 SUBTEAM C — TELEMETRY, QA & EVIDENCE

**Bối cảnh:** Chưa có script telemetry/inject/test. Việc tuần này là **tạo dữ liệu để chạy, chạy ≥10 scenario, gom bằng chứng + slides**. Phụ thuộc executor (A) chạy được — trong lúc chờ, dùng `mock_ai_server.py` + `CDO_K8S_MOCK=true` để dựng script trước.

---

### C-01 — Preprocessor RE2/RE3 (CSV→telemetry JSON) · **MUST** · C2 · T2
🎯 Biến dataset CSV thành telemetry đúng schema (12 signal), scrub PII.
🔧 Tạo `executor/scenarios/preprocess.py`:
   ```python
   import csv, json, uuid, sys
   TENANT = "6c8b4b2b-4d45-4209-a1b4-4b532d56a31c"
   def row_to_signal(r):
       return {"ts": r["ts"], "tenant_id": TENANT, "service": r["service"],
               "signal_name": r["signal_name"], "value": _num(r["value"]),
               "labels": {"system": "E-COMMERCE", "namespace": r["namespace"],
                          "deployment": r["deployment"]}}
   def _num(v):
       try: return float(v)
       except: return v
   # đọc metrics.csv → list signal → ghi telemetry_window JSON
   ```
2. Scrub PII: regex xóa email/token/connection-string khỏi `application_log_event.value`.
✅ Kiểm tra: output validate được bằng schema telemetry-contract; không còn PII.
📎 Evidence: 1 file telemetry JSON mẫu.

---

### C-02 — Inject scripts cho từng pattern · **MUST** · C2 · T2–T3
🎯 Script bắn telemetry để trigger từng pattern. Đã có mẫu `scenarios/tc01_service_stuck.json`.
🔧 Tạo thêm các scenario JSON (copy mẫu, đổi `signal_name`/`value`/`tenant_namespace`):
   - `tc04_oom.json`: `container_resource_usage` value cao + `pod_oom_event`.
   - `tc05_queue.json`: `queue_backlog` value 15000, tenant-b.
   - `tc06_secret.json`: `secret_expiry_warning` value 7.
   - `tc07_cross_tenant.json`: incident tenant-a (để test deny — dùng mock AI trả target tenant-b).
2. Cách chạy 1 scenario: `python main.py scenarios/<file>.json`.
✅ Kiểm tra: mỗi script chạy ra đúng pattern_type/action mong đợi.
📎 Evidence: log mỗi scenario.

---

### C-03 — SQS forwarder/worker · **SHOULD** · C2 · T3
🎯 Đẩy telemetry qua SQS buffer rồi forward sang `/v1/detect` (chứng minh backpressure ≤100 RPS).
🔧 Viết worker: đọc SQS (queue từ B-03) → batch → POST `/v1/detect`. Dùng boto3 `receive_message`.
✅ Kiểm tra: bắn 200 message → worker giữ nhịp ≤100 RPS, không drop.
📎 Evidence: log throughput.

---

### C-04 — Dashboard Grafana/Prometheus · **SHOULD** · C2 · T3
🔧 Cài kube-prometheus-stack qua Helm; import dashboard latency/error/memory/restart cho tenant-a/b.
✅ Kiểm tra: dashboard hiện metric thật từ podinfo.
📎 Evidence: screenshot dashboard.

---

### C-05 — Scenario simulation runner (≥10 scenario, ≥4h) · **MUST** · C1 · T3–T4
🎯 Chạy đủ ≥10 scenario trong cửa sổ ≥4h → tính auto-resolve rate.
🔧 Tạo `executor/scenarios/run_all.py`:
   ```python
   import glob, subprocess, time, json
   results = []
   for f in sorted(glob.glob("scenarios/tc*.json")):
       out = subprocess.run(["python","main.py",f], capture_output=True, text=True)
       outcome = out.stdout.strip().splitlines()[-1]
       results.append({"scenario": f, "outcome": outcome,
                       "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
       time.sleep(5)   # giãn cho đủ window; lặp lại set để đạt 4h
   json.dump(results, open("scenarios/run_report.json","w"), indent=2)
   ```
2. Để đạt 4h: lặp set scenario nhiều vòng (cron/loop), ghi timestamp đầu–cuối.
✅ Kiểm tra: `run_report.json` có ≥10 dòng, timestamp cách nhau ≥4h.
📎 Evidence: run_report.json.

---

### C-06 — Chạy TC-01..06 + auto-resolve rate · **MUST** · C1 · T3–T4
🎯 Đo `auto_resolved_count / total ≥ 60%`.
🔧 Từ `run_report.json`, đếm outcome `auto_resolved`. Điền bảng "Tóm tắt kết quả" trong [docs/07_test_eval_report_v1.0_Duc.md](docs/07_test_eval_report_v1.0_Duc.md).
✅ Kiểm tra: rate ≥60%, có bảng số thật.
📎 Evidence: bảng auto-resolve + run_report.

---

### C-07 — Chạy TC-07..21 (safety/failure) · **MUST** · C1 · T4
🎯 Chứng minh deny đúng từng case (cross-tenant, action lạ, thiếu verify_policy, AI 503...).
🔧 Mỗi TC: dùng mock AI trả response "xấu" tương ứng (sửa `mock_ai_server.py` trả target sai/action lạ), chạy, kiểm audit reason.
✅ Kiểm tra: mỗi TC ra đúng audit reason (vd `denied_cross_tenant`), 0 mutation sai.
📎 Evidence: log audit từng TC.

---

### C-08 — Multi-tenant isolation suite · **MUST** · C1 · T3
🎯 Cross-tenant = SEV1. Chứng minh deny ở mọi lớp.
🔧 Chạy: (1) safety gate test cross-tenant (đã có trong `test_safety_gate.py`); (2) RBAC `kubectl auth can-i` (B-11); (3) ArgoCD AppProject chặn sync sai namespace.
✅ Kiểm tra: 100% cross-tenant bị deny, 0 mutation thành công.
📎 Evidence: output 3 lớp.

---

### C-09 — Load test k6 · **CUT** · C1 · T4
🔧 k6 script bắn 100 events/phút trong 10 phút vào ingestion; ghi p99, error rate. Nếu trễ → để TBD.
📎 Evidence: k6 summary.

---

### C-10 — Audit query theo correlation_id · **MUST** · C3 · T4
🎯 Chứng minh audit query được (rubric).
🔧 Cách nhanh: `aws s3 cp s3://<bucket>/audit/<tenant>/<cid>.json - | python -m json.tool`. Nâng cao: tạo Athena table trỏ vào bucket, query `WHERE correlation_id=...`.
✅ Kiểm tra: trả full chuỗi event 1 incident.
📎 Evidence: output query.

---

### C-11 — Điền 07_test_eval (measured) · **MUST** · C1+C3 · T4
🔧 Điền cột Measured/Actual trong các bảng SLO + Failure Analysis của [07_test_eval](docs/07_test_eval_report_v1.0_Duc.md) bằng số thật từ C-05..08. Không điền số giả.
✅ Kiểm tra: không còn TBD ở phần đã chạy.
📎 Evidence: commit doc.

---

### C-12 — Gói evidence pack · **MUST** · C3 · T4–T5
🔧 Sắp xếp `evidence/` đủ: run_report, audit samples, kubectl outputs, screenshots, cost. Theo `capstone-phase2/reference/CAPSTONE_EVIDENCE_PACK_FORMAT.md`.
✅ Kiểm tra: đủ artifact theo checklist Pack #2.
📎 Evidence: cây thư mục `evidence/`.

---

### C-13 — SLIDES.pdf + demo video · **MUST** · C3 · T4–T5
🎯 Phần present ăn điểm lớn. Demo lõi = A-14 (auto-resolve thật) + cross-tenant deny + Kyverno block.
🔧 Slide: kiến trúc, differentiation (3-lớp safety, Pre-Decide Gate, CDO self-capture snapshot), số liệu auto-resolve/cost. Video: quay E2E auto_resolved + 1 deny.
✅ Kiểm tra: video chạy được, slide ≤ thời lượng pitch.
📎 Evidence: SLIDES.pdf + demo-video.mp4.

---

### C-14 — curveball-responses.md · **MUST** · C3 · T2 & T4
🔧 Ngay sau curveball #2 (T2 16h) và #3 (T4 14h), ghi: đề bài, cách CDO-02 phản ứng, file/đổi gì. Mẫu mỗi mục: *Context · Quyết định · Thay đổi code/doc · Kết quả*.
✅ Kiểm tra: 2 mục ghi trong ngày curveball.
📎 Evidence: commit curveball-responses.md.

---

### C-15 — individual-pitches.md · **MUST** · cả team · T4
🎯 Chống free-rider: mỗi người walk-through được commit của mình.
🔧 Mỗi thành viên viết 3–5 câu: tôi làm task gì, commit nào, quyết định kỹ thuật + trade-off.
✅ Kiểm tra: 10 mục, mỗi mục có commit SHA.
📎 Evidence: file + SHA.

---

### C-16 — Giữ docs sync nếu contract đổi · **MUST** · C3 · ongoing
🔧 Nếu curveball đổi contract: cập nhật header "sync contract-new-X" + bảng I/O + SLA + error table **trong cùng PR** với code. Grep tìm reference cũ: `grep -rn "contract-new" docs/`.
✅ Kiểm tra: `grep` không còn version cũ lẫn lộn.
📎 Evidence: commit doc sync.

---
---

# 🔗 Critical path & quy tắc cắt scope (A1 quyết)

```
B-01 EKS ─┬─► A-02/03/04 (K8s thật) ─┐
B-03 audit─┘                          ├─► A-14 E2E thật ─► C-05/06/07 scenario ─► C-11/12/13 evidence+slide
AI image ─► B-10 ─► A-08 integrate ──┘
```
- **B không block A:** chưa có cluster → A dev tiếp bằng `CDO_K8S_MOCK=true` + `mock_ai_server.py`.
- **Thứ tự cắt khi trễ:** C-09 load test → A-13 multi-step → A-12 circuit breaker → B-09 deferred (hạ queue/secret về **designed-only**; vẫn đạt ≥3 build + ≥2 design).
- **KHÔNG bao giờ cắt:** safety gate, cross-tenant deny (C-08), audit trail (A-07/C-10), ≥10 scenario + auto-resolve (C-05/06), slides+demo (C-13).

# 📌 Nghi thức hằng ngày (mọi người)
- Sáng: pull 1 Jira task → In Progress. Trong ngày: comment ≥1 lần (progress/blocker/ETA).
- Close task **bắt buộc** gắn evidence link. Không backdate, không batch 5 task/1 phút.
- 14h standup ≤30s/người: Done / Doing / Blocker.
- Escalate mentor ngay khi: 2 ngày cùng blocker · AI–CDO lệch contract · build <50% giữa tuần.
