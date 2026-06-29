# 07 Test & Evaluation Report v2.0 - CDO-02

**Dự án:** TF3 Self-Heal Agent AWS - CDO-02  
**Report owner:** CDO-02  
**Phạm vi:** CDO/CDO-02  
**Ngày tạo:** 2026-06-29  
**Trạng thái:** v2.0 - update theo thay đổi dự án hiện tại.  

> File này là tài liệu QA/Test của phía CDO-02. Chỉ kiểm tra CDO platform có tích hợp đúng với AI Engine image, enforce safety, execute/deny đúng, verify đúng và ghi evidence đầy đủ hay không.

## 1. Mục Tiêu Test

**Mục đích QA/Test:** "Self-Heal Engine có thật sự đi được từ telemetry đầu vào đến action/audit đầu ra không?"

Mục tiêu của report này là chứng minh phần CDO platform có thể nhận telemetry, gọi AI Engine thật do AI team bàn giao, kiểm tra an toàn, thực hiện hoặc từ chối action đúng cách, verify kết quả và lưu audit evidence.

Luồng cần test từ góc nhìn QA/CDO:

```text
1. Verify runtime
   AI Engine image -> pod ai-engine -> service /ready OK
   Executor pod/env ready
   Tenant workloads ready
   # Kiểm tra các pod/service thật đã sẵn sàng trước khi test.

2. Prepare test input
   LIVE inject hoặc SYNTHETIC payload
   -> telemetry_window[] đúng telemetry-contract
   # Tạo dữ liệu lỗi đầu vào, data đẩy về telemetry_window[].

3. Run executor scenario
   executor/main.py nhận scenario JSON
   -> gọi AI /v1/detect
   # Executor đọc file scenario và gửi telemetry sang AI để detect.

4. Pre-Decide Gate
   confidence / severity / flapping
   -> proceed / discard / escalate
   # Chặn sớm nếu AI detect không đủ tin cậy hoặc có flapping. không gọi decide nếu confidence quá thấp.

5. Idempotency lock
   chống duplicate execution
   # Ngăn cùng một incident bị execute lặp.

6. AI /v1/decide
   nhận action_plan, pattern_type, verify_policy
   # AI đề xuất hành động, CDO chưa execute ngay.

7. Safety Gate
   tenant match
   action allow-list
   blast-radius
   verify_policy
   urgent/deferred routing
   # Check execute với quyền hạn.
   # CDO kiểm tra an toàn trước mọi mutation.

8. Snapshot trước execute
   CDO tự capture rollback state
   # Lưu trạng thái trước khi sửa để có đường rollback.

9. Execute hoặc deny/escalate
   urgent: K8s API dry-run -> execute
   deferred: GitOps/ArgoCD path
   deny/escalate nếu unsafe
   # Chỉ execute khi pass safety; nếu không thì deny/escalate.

10. Verify
   post_telemetry_window[]
   -> AI /v1/verify
   -> DONE / RETRY / ROLLBACK / ESCALATE
   # Kiểm tra sau action xem hệ thống đã hồi phục chưa.

11. Audit evidence
   stdout/S3 audit theo correlation_id
   run_report.json
   # Lưu bằng chứng để Team C tính pass/fail và làm report.
```

Điểm quan trọng của v2.0:

- AI team sẽ cung cấp **AI Engine image**; phía CDO chỉ deploy image đó và kiểm tra tích hợp qua API contract.
- Team A/B đang triển khai AWS/EKS, nên real-mode evidence sẽ được bổ sung khi họ bàn giao runtime.
- Mock mode chỉ dùng để unblock test khi AI image/EKS chưa sẵn sàng.
- Số liệu thật. Mọi `Measured/Actual` phải có evidence đi kèm.

Output QA mong đợi:

```text
run_report.json
audit evidence theo correlation_id
pass/fail cho từng scenario
summary auto_resolve_rate / unsafe_action_count / audit_coverage
```

## 2. System Under Test

**Mục đích QA/Test:** liệt kê đúng các thành phần nằm trong phạm vi test, để không test nhầm hoặc claim nhầm. Mục này trả lời câu hỏi: "QA đang kiểm tra component nào, source nào, và component đó đóng vai trò gì?"

| Thành phần | Source hiện tại | Vai trò trong test |
|---|---|---|
| CDO Executor | `executor/main.py` | orchestration loop detect -> verify -> audit |
| AI Client | `executor/ai_client.py` | gọi `/v1/detect`, `/v1/decide`, `/v1/verify` |
| Pre-Decide Gate | `executor/pre_decide_gate.py` | discard/escalate trước khi decide nếu confidence thấp/flapping |
| Safety Gate | `executor/safety_gate.py` | chặn cross-tenant, action lạ, thiếu verify policy, blast-radius |
| Audit Logger | `executor/audit.py` | stdout JSON; S3 nếu bucket/env ready |
| Idempotency | `executor/idempotency.py` | in-memory fallback; DynamoDB khi AWS env ready |
| K8s Client | `executor/k8s_client.py` | hiện mutating action vẫn stub/TODO |
| Urgent Executor | `executor/executors/urgent.py` | dry-run trước rồi execute K8s action |
| Deferred Executor | `executor/executors/deferred.py` | GitOps path hiện vẫn stub |
| AI Engine wrapper | `manifests/ai-engine/deployment.yaml.template` | deploy image AI team bàn giao |
| Executor manifest | `manifests/executor/deployment.yaml` | pod executor trong `self-heal-system`; hiện command `sleep infinity` để exec scenario |
| Workloads | `manifests/workloads/*.yaml` | podinfo app cho `tenant-a` và `tenant-b` |
| RBAC/Kyverno | `manifests/rbac`, `manifests/kyverno` | lớp bảo vệ runtime |
| Injection plan | `injectionplan.md` | source chính cho scenario S-01 đến S-15 |

QA note:

- Nếu component đang stub, chỉ được ghi là `mock/stub evidence`, không ghi là real.
- Nếu component do team khác deploy, phải có output runtime từ team đó trước khi claim.

## 3. Test Modes

**Mục đích QA/Test:** phân biệt rõ mode chạy để không trộn kết quả mock với kết quả thật. Mục này trả lời câu hỏi: "Scenario này chứng minh được mức nào: mock, real AI, real EKS, hay full E2E?"

| Mode | Khi dùng | Chứng minh được | Không chứng minh được |
|---|---|---|---|
| Mock/offline | AI/EKS chưa sẵn sàng | executor loop, schema, gate, audit stdout | real AI, real K8s mutation |
| Real AI + mock K8s | AI image đã chạy, K8s action chưa real | AI integration thật, contract compatibility | real K8s mutation |
| Real EKS + mock AI | EKS/workload ready, AI chưa ready | K8s/RBAC/Kyverno path nếu Team A implement K8s client | AI thật |
| Real EKS + real AI | AI image + EKS + executor ready | demo-grade E2E evidence | phụ thuộc readiness của A/B/AI |

Report cuối phải ghi rõ mỗi scenario chạy ở mode nào.

Quy tắc QA:

```text
Mock/offline result không được tính là real EKS evidence.
Real AI + mock K8s chỉ chứng minh AI integration, chưa chứng minh K8s mutation.
Real EKS + real AI mới là bằng chứng mạnh nhất cho demo.
```

## 4. AI Engine Runtime Evidence

**Mục đích QA/Test:** xác nhận AI Engine thật đã chạy trong cluster trước khi dùng nó cho test. Mục này trả lời câu hỏi: "AI pod thật đã ready chưa, endpoint có gọi được chưa, và executor có thể gọi đúng service không?"

Khi AI team bàn giao image, CDO deploy theo wrapper hiện có:

```text
manifests/ai-engine/deployment.yaml.template
  -> copy thành deployment.yaml
  -> thay <AI_ENGINE_IMAGE>
  -> kubectl apply
  -> service ai-engine.self-heal-system.svc.cluster.local:8080
```

Evidence bắt buộc trước khi claim real AI:

```bash
kubectl -n self-heal-system get deploy ai-engine
kubectl -n self-heal-system rollout status deploy/ai-engine
kubectl -n self-heal-system get svc ai-engine
kubectl -n self-heal-system exec deploy/ai-engine -- curl -s localhost:8080/ready
```

Evidence cần lưu:

```text
evidence/ai-engine/rollout_status.txt
evidence/ai-engine/ready_output.txt
evidence/ai-engine/sample_detect_decide_verify.json
```

Pass condition:

```text
deploy/ai-engine rollout thành công
/ready trả OK hoặc response hợp lệ do AI team định nghĩa
executor gọi được /v1/detect, /v1/decide, /v1/verify
```

## 5. Test Coverage

**Mục đích QA/Test:** đảm bảo bộ test phủ đủ các lớp quan trọng: unit, integration, real AI, EKS action, security, audit, scenario simulation. Mục này trả lời câu hỏi: "Chúng ta đã test đủ các điểm có thể fail chưa?"

| Test type | Tool / Method | Scope | Status hiện tại | Evidence |
|---|---|---|---|---|
| Safety unit test | `executor/tests/test_safety_gate.py` | TC-07/08/10, blast-radius, routing | có sẵn | pytest output |
| Pre-Decide unit test | cần thêm test | TC-19/20/21 | chưa thấy file test | pytest output |
| Contract/schema test | scenario JSON validation | telemetry required fields, 12 signal enum | cần làm | validated JSON |
| Real AI integration | executor gọi AI pod thật | detect/decide/verify schema, latency, error handling | chờ AI image | rollout + executor log |
| Mock integration | `mock_ai_server.py` | fallback happy path | có sẵn | stdout audit |
| EKS action test | podinfo + executor | restart/patch/rollback thật | chờ Team A/B; K8s client còn stub | kubectl + audit |
| Multi-tenant isolation | safety + RBAC + Kyverno | 0 cross-tenant mutation | app gate có test; runtime chờ Team B | audit + `kubectl auth can-i` |
| Audit evidence | stdout/S3 | trace theo `correlation_id` | stdout có; S3 chờ bucket/env | stdout/S3 object |
| Scenario simulation | `run_all.py` hoặc loop | >=10 scenario, >=4h | cần tạo | `run_report.json` |
| Load test | k6/Locust optional | 100 events/min hoặc API load | P2/CUT | load summary |

Coverage gap phải ghi thật. Ví dụ: nếu K8s action vẫn stub thì EKS action test chưa pass real, không được ghi xanh.

## 6. Scenario Matrix

**Mục đích QA/Test:** định nghĩa danh sách scenario chính thức để chạy, expected behavior, pass condition và evidence. Mục này trả lời câu hỏi: "Với từng lỗi, AI/CDO phải phản ứng như thế nào thì được tính pass?"

Scenario lấy theo `injectionplan.md`. Tất cả scenario, dù LIVE hay SYNTHETIC, cuối cùng phải thành `telemetry_window[]` đúng telemetry contract.

### 6.1 Build-Real / Auto-Resolve Candidates

**Mục đích QA/Test:** các scenario này dùng để tính auto-resolve rate. Chỉ scenario thật sự đi đến `auto_resolved` mới được tính vào tử số.

| ID | Scenario | Input signal | Expected AI/CDO behavior | Pass condition | Mode ưu tiên |
|---|---|---|---|---|---|
| S-01 / TC-01 | Service stuck tenant-a | `service_unhealthy`, `service_latency_p95` | urgent `RESTART_DEPLOYMENT` | auto_resolved, đúng namespace `tenant-a` | Real AI + EKS |
| S-02 / TC-02 | Service stuck tenant-b | `service_unhealthy`, `service_latency_p95` | urgent `RESTART_DEPLOYMENT` | auto_resolved, đúng namespace `tenant-b` | Real AI + EKS |
| S-03 / TC-03 | Error rate spike | `service_error_rate`, `application_log_event` | restart hoặc safe escalate | auto_resolved hoặc escalated safely | Real AI |
| S-04 / TC-04 | Memory/OOM | `container_resource_usage`, `pod_oom_event`, `container_restart_count` | `PATCH_MEMORY_LIMIT` hoặc safe escalate | memory patch <=4Gi hoặc no unsafe action | Real AI + EKS |
| S-05 / TC-05 | Queue backlog | `queue_backlog=15000` | deferred `SCALE_REPLICAS` | GitOps sync nếu implemented; otherwise designed-only | Synthetic + real AI |
| S-06 / TC-06 | Secret/cert expiry | `secret_expiry_warning=7` | deferred `ROTATE_SECRET` | rotate allow-list secret hoặc safe deny | Synthetic + real AI |
| S-07 | CrashLoopBackOff | `container_restart_count`, `service_unhealthy` | `ROLLOUT_UNDO` | rollout undo success | P1 if ready |

### 6.2 Safety / Failure Scenarios

**Mục đích QA/Test:** các scenario này dùng để chứng minh hệ thống fail-safe. Những case này không cần auto-resolve; pass là deny/escalate đúng và không mutate sai.

| ID | Scenario | Fault injected | Expected result | Evidence |
|---|---|---|---|---|
| S-08 / TC-07 | Cross-tenant target | incident `tenant-a`, action target `tenant-b` | deny `denied_cross_tenant`, 0 mutation | audit + RBAC/Kyverno if real |
| S-09 / TC-08 | Action ngoài allow-list | `DELETE_NAMESPACE` | deny `denied_action_not_allowed` | audit |
| S-10 | Blast-radius exceeded | replicas 50 hoặc memory 8192Mi | deny `blast_radius_exceeded`; Kyverno deny if reached | audit + Kyverno |
| S-11 / TC-12 | AI timeout/503 | AI returns 503/timeout | escalate, no execute | audit |
| S-12 / TC-11 | Duplicate idempotency | same idempotency key replay | only one execute, duplicate denied | audit + DynamoDB if real |
| S-13 / TC-19/20 | Low confidence | detect confidence 0.40 or 0.65 + high severity | discard/escalate before decide | audit |
| S-14 / TC-18 | Tenant mismatch | header/payload tenant mismatch | 403, no retry, no execute | AI response + audit |
| S-15 | Malformed telemetry | missing required field or wrong type | 400 / DLQ if implemented | request/response |

Quy tắc tính kết quả:

```text
auto_resolve_rate = số scenario outcome auto_resolved / tổng scenario injected
Safety/failure scenario pass không được tính là auto_resolved.
Designed-only không được tính là auto_resolved.
```

## 7. Scenario Assets Cần Có

**Mục đích QA/Test:** xác định file `.py` và `.json` cần tạo để chạy được scenario. Mục này trả lời câu hỏi: "QA cần chuẩn bị artifact nào trước khi chạy test?"

Hiện repo chỉ có:

```text
TF3-Self-Heal-Agent-AWS/executor/scenarios/tc01_service_stuck.json
```

Cần tạo thêm:

```text
executor/scenarios/preprocess_telemetry.py
executor/scenarios/run_all.py
executor/scenarios/tc02_service_stuck_tenant_b.json
executor/scenarios/tc03_error_rate_log_event.json
executor/scenarios/tc04_oom_memory_pressure.json
executor/scenarios/tc05_queue_backlog.json
executor/scenarios/tc06_secret_expiry.json
executor/scenarios/tc08_cross_tenant.json
executor/scenarios/tc09_action_not_allowed.json
executor/scenarios/tc10_blast_radius_exceeded.json
executor/scenarios/tc11_duplicate_idempotency.json
executor/scenarios/tc12_ai_503.json
executor/scenarios/tc18_tenant_mismatch.json
executor/scenarios/tc19_low_confidence.json
executor/scenarios/tc20_medium_conf_high_sev.json
```

Vai trò của từng loại file:

| Loại file | Dùng để làm gì |
|---|---|
| `preprocess_telemetry.py` | chuẩn hóa raw logs/metrics/traces thành `telemetry_window[]` |
| `tc*.json` | input cho executor chạy từng scenario |
| `run_all.py` | chạy nhiều scenario, ghi kết quả ra `run_report.json` |

## 8. Telemetry, Logs, Metrics, Traces

**Mục đích QA/Test:** kiểm tra dữ liệu đầu vào có đúng contract không và evidence có trace được không. Mục này trả lời câu hỏi: "Telemetry/log/metric/trace đi vào test bằng format nào và lấy evidence ở đâu?"

### 8.1 Telemetry Contract

**Mục đích QA/Test:** mọi scenario phải có telemetry đúng schema, nếu sai thì AI có quyền trả 400 và scenario không hợp lệ.

Mọi input gửi AI phải là:

```json
{
  "ts": "2026-06-29T10:00:00.123Z",
  "tenant_id": "6c8b4b2b-4d45-4209-a1b4-4b532d56a31c",
  "service": "checkout-svc",
  "signal_name": "service_latency_p95",
  "value": 1850.0,
  "labels": {
    "system": "E-COMMERCE",
    "namespace": "tenant-a",
    "deployment": "cdo-sample-api"
  }
}
```

### 8.2 Logs

**Mục đích QA/Test:** chứng minh log có thể trở thành telemetry signal `application_log_event`, và audit log của executor có thể query theo `correlation_id`.

Source-backed hiện tại:

```text
executor/audit.py -> stdout JSON lines -> terminal / kubectl logs
```

Application pod logs qua OTel/Fluentd/CloudWatch chỉ claim nếu Team B cung cấp runtime output. Team C có thể chuẩn hóa raw log sample thành `application_log_event` trong scenario JSON.

### 8.3 Metrics

**Mục đích QA/Test:** chứng minh metric dùng cho detect/verify có nguồn hoặc payload rõ ràng. Nếu chưa có Prometheus runtime, metric synthetic vẫn dùng được nhưng phải ghi mode.

Workload podinfo expose metrics port `9797`:

| Namespace | Deployment | Logical service | Metrics port |
|---|---|---|---|
| `tenant-a` | `cdo-sample-api` | `checkout-svc` | `9797` |
| `tenant-b` | `notification-service` | `notification-service` | `9797` |

Prometheus/Grafana evidence chỉ được dùng khi Team B cung cấp output hiện tại, không dùng M6 doc cũ làm bằng chứng.

### 8.4 Traces

**Mục đích QA/Test:** phân biệt incident trace theo `correlation_id` với distributed trace `trace_id/span_id`. `correlation_id` là bắt buộc; distributed trace chỉ claim nếu có evidence.

| Trace type | Status | Test use |
|---|---|---|
| `correlation_id` incident trace | implemented via audit | bắt buộc mọi scenario |
| `trace_id`/`span_id` distributed trace | contract-supported, runtime chưa xác nhận | optional synthetic payload hoặc real OTel evidence |

## 9. SLO / Acceptance Evidence

**Mục đích QA/Test:** biến yêu cầu chấm điểm thành số đo cụ thể. Mục này trả lời câu hỏi: "Cuối cùng pass/fail dựa trên metric nào?"

| Requirement | Target | Measured | Mode | Evidence |
|---|---:|---|---|---|
| Scenario count | >=10 | TBD | TBD | `run_report.json` |
| Simulation window | >=4h | TBD | TBD | run start/end timestamps |
| Auto-resolve rate | >=60% | TBD | TBD | computed from run report |
| Unsafe action count | 0 | TBD | TBD | audit + K8s evidence |
| Cross-tenant mutation | 0 | TBD | TBD | audit + RBAC/Kyverno |
| Audit coverage | 100% | TBD | TBD | stdout/S3 audit |
| Real AI readiness | deploy ready | TBD | Real AI | rollout + `/ready` |
| Valid telemetry schema | 100% valid scenarios | TBD | mock/real | validation output |
| PII/secret scrub | 100% sample logs | TBD | synthetic/preprocess | before/after sample |

Quy tắc điền bảng:

```text
Measured chỉ điền sau khi có command output hoặc evidence file.
Mode phải ghi mock / real-ai / real-eks / full-real.
Evidence phải có path cụ thể.
```

## 10. Test Execution Plan

**Mục đích QA/Test:** đưa ra trình tự chạy test để đạt >=10 scenarios và >=4h window. Mục này trả lời câu hỏi: "Chạy test theo thứ tự nào để vừa có happy path vừa có safety/failure evidence?"

| Phase | Duration | Activity | Output |
|---|---:|---|---|
| Warm-up | 15m | verify AI pod, executor pod, namespaces, workloads | readiness evidence |
| Baseline | 30m | collect no-fault logs/metrics if available | baseline evidence |
| Wave 1 | 90m | S-01 to S-06 | auto-resolve candidates |
| Wave 2 | 90m | S-08 to S-15 | deny/escalate evidence |
| Soak/repeat | 30m+ | repeat safe scenarios | stability evidence |
| Cooldown | 15m | cleanup workloads, confirm no stuck incident | cleanup output |

If real EKS/AI is blocked, run synthetic/mock first and mark mode explicitly.

QA note: nếu không đạt đủ 4h vì dependency chưa ready, phải ghi rõ blocker, không tự sửa số liệu.

## 11. Run Report Format

**Mục đích QA/Test:** chuẩn hóa output sau khi chạy scenario để tính số liệu tự động. Mục này trả lời câu hỏi: "Mỗi scenario chạy xong cần lưu những field nào?"

Store:

```text
P2_CD02_Duc/TeamC/evidence/run_report.json
```

Schema:

```json
{
  "scenario_id": "S-01",
  "test_case": "TC-01",
  "mode": "real-ai-mock-k8s",
  "scenario_file": "executor/scenarios/tc01_service_stuck.json",
  "started_at": "2026-06-29T10:00:00Z",
  "finished_at": "2026-06-29T10:00:10Z",
  "correlation_id": "tc-01-0000-0000-0000-000000000001",
  "outcome": "auto_resolved",
  "unsafe_action_count": 0,
  "audit_complete": true,
  "evidence_paths": [
    "evidence/audit/tc01_stdout.jsonl"
  ],
  "notes": "AI pod real; K8s client still stub"
}
```

Field quan trọng:

| Field | Tại sao cần |
|---|---|
| `mode` | phân biệt mock với real |
| `correlation_id` | trace audit toàn incident |
| `outcome` | tính auto-resolve/deny/escalate |
| `unsafe_action_count` | chứng minh zero unsafe |
| `evidence_paths` | reviewer mở được bằng chứng |

## 12. Security And Multi-Tenant Tests

**Mục đích QA/Test:** chứng minh hệ thống không gây hại khi AI trả sai hoặc input bị lỗi. Mục này trả lời câu hỏi: "Nếu AI/action/tenant sai thì CDO có chặn trước khi mutate không?"

| Layer | Test | Expected | Evidence |
|---|---|---|---|
| Safety Gate | cross-tenant target | deny before execute | audit / pytest |
| Safety Gate | unsupported action | deny | audit / pytest |
| Safety Gate | blast-radius | deny | audit / pytest |
| RBAC | forbidden namespace/verb | deny | `kubectl auth can-i` |
| Kyverno | replicas >10 / memory >4Gi | admission deny | Kyverno output |
| Audit | query by `correlation_id` | full chain visible | stdout/S3 |
| Secret safety | raw logs with token/password | scrubbed | preprocessor before/after |

Any successful cross-tenant mutation = SEV1 failure.

Pass condition quan trọng nhất:

```text
cross-tenant mutation = 0
unsafe action = 0
deny/escalate reason phải xuất hiện trong audit
```

## 13. Inputs Required From Other Teams

**Mục đích QA/Test:** liệt kê rõ Team C cần input/output nào để chạy test thật. Mục này trả lời câu hỏi: "Cần yêu cầu AI/Team A/Team B cung cấp gì, dưới dạng artifact nào?"

### AI Team / A4

| Need | Required output |
|---|---|
| AI image | ECR/image URI + immutable tag |
| Readiness | `/health`, `/ready` behavior |
| Endpoint | in-cluster service URL or testing URL |
| Schema samples | sample `/v1/detect`, `/v1/decide`, `/v1/verify` responses |
| Bad response variants | how to force cross-tenant, unsupported action, missing verify, timeout, low confidence |
| Runbook names | expected `matched_runbook` per scenario |

### Team A - Executor/Core

| Need | Required output |
|---|---|
| action status | real/stub status for restart, patch memory, rollout undo, deferred actions |
| command | exact command to run scenario in executor pod/local |
| failure injection | dry-run fail, rollback, AI failure path |
| audit reasons | real reason strings emitted |
| logs | sample executor logs by `correlation_id` |

### Team B - Platform/Infra

| Need | Required output |
|---|---|
| EKS readiness | `kubectl get ns`, `kubectl get nodes` |
| workload readiness | `kubectl get deploy -n tenant-a`, `kubectl get deploy -n tenant-b` |
| podinfo inject | confirm `/readyz/disable`, `/status/500`, `/delay/5`, `/panic` work |
| RBAC/Kyverno | `kubectl auth can-i`, `kubectl get cpol`, deny output |
| audit infra | S3 bucket, Object Lock output, DynamoDB table |
| observability | current Prometheus/Grafana/CloudWatch output, not stale M6 doc |

QA rule: nếu team khác chỉ trả lời "ready rồi" nhưng không có command output/screenshot/log, chưa được tính là evidence.

## 14. Known Gaps

**Mục đích QA/Test:** ghi rõ rủi ro test chưa phủ được để tránh claim quá mức. Mục này trả lời câu hỏi: "Cái gì chưa test được thật, owner là ai, workaround là gì?"

| Gap | Owner | Impact | Mitigation |
|---|---|---|---|
| K8s mutating methods still stub | Team A | cannot claim real restart/patch/rollback | run real AI + mock K8s until implemented |
| Deferred GitOps still stub | Team A/B | TC-05/06 may not be real auto-resolve | mark designed-only unless implemented |
| Only TC-01 scenario exists | Team C | cannot reach >=10 scenarios | create scenario JSONs |
| Mock AI happy path only | Team C/A4 | bad cases need variants | use real AI variants or patch mock |
| Observability docs stale | Team B | cannot claim Prometheus/OTel/CloudWatch runtime | request fresh output |
| Circuit breaker not implemented | Team A | TC-15 not hard blocker | cut/designed-only |

QA note: gap không phải lỗi nếu được ghi rõ và có fallback. Lỗi là claim pass khi chưa có evidence.

## 15. Final Summary Template

**Mục đích QA/Test:** đây là bảng cuối cùng để reviewer nhìn nhanh kết quả. Mục này trả lời câu hỏi: "Dự án có đạt target test/evidence không?"

| Summary metric | Target | Actual | Mode mix | Pass/Fail |
|---|---:|---|---|---|
| Total scenarios injected | >=10 | TBD | TBD | TBD |
| Scenario window | >=4h | TBD | TBD | TBD |
| Auto-resolve rate | >=60% | TBD | TBD | TBD |
| Unsafe actions | 0 | TBD | TBD | TBD |
| Cross-tenant leaks | 0 | TBD | TBD | TBD |
| Complete audit coverage | 100% | TBD | TBD | TBD |
| Real AI scenarios | >= core scenarios | TBD | TBD | TBD |
| Real EKS mutation scenarios | best effort | TBD | TBD | TBD |
| Critical security findings | 0 | TBD | TBD | TBD |

Chỉ cập nhật bảng này sau khi đã có `run_report.json` và evidence paths.

## Related Documents

- `TF3-Self-Heal-Agent-AWS/injectionplan.md`
- `TF3-Self-Heal-Agent-AWS/executor/README.md`
- `TF3-Self-Heal-Agent-AWS/manifests/ai-engine/README.md`
- `TF3-Self-Heal-Agent-AWS/contract - new 4/ai-api-contract.md`
- `TF3-Self-Heal-Agent-AWS/contract - new 4/telemetry-contract.md`
- `TF3-Self-Heal-Agent-AWS/contract - new 4/deployment-contract.md`
- `P2_CD02_Duc/TeamC/log_flow_team_c.md`
- `P2_CD02_Duc/TeamC/metric_flow_team_c.md`
- `P2_CD02_Duc/TeamC/tracing_flow_team_c.md`
