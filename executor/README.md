# CDO Self-Heal Executor — Skeleton

Trái tim runtime của CDO-02: vòng `detect → pre-decide gate → decide → safety gate → snapshot → execute → verify → audit`. Align với **contract-new-4**.

> Trạng thái: **skeleton chạy được**. Main loop + Pre-Decide Gate + Safety Gate + AI client (error/retry policy) + audit đã hoàn chỉnh. Phần K8s/AWS/Deferred là stub có TODO(W12).

## Cấu trúc module

| File | Vai trò | Mức |
|---|---|---|
| `main.py` | **Orchestration loop** + CLI chạy 1 scenario | ✅ đầy đủ |
| `pre_decide_gate.py` | 7-condition gate sau detect (confidence/severity/flapping/maintenance) | ✅ đầy đủ |
| `safety_gate.py` | **Safety gate** (tenant match, allow-list, blast-radius, routing, verify_policy) | ✅ đầy đủ |
| `ai_client.py` | HTTP client 3 endpoint + error policy §4 (400/401/403/409/429/500×2/503) | ✅ đầy đủ |
| `models.py` | Dataclass I/O schema (Detect/Decide/Verify) | ✅ đầy đủ |
| `errors.py` | Exception map theo HTTP code | ✅ đầy đủ |
| `config.py` | Config env-driven (tenant, endpoint, caps, namespaces) | ✅ đầy đủ |
| `idempotency.py` | DynamoDB conditional write (decide-only) | 🟡 logic xong, cần boto3+table |
| `audit.py` | Audit theo correlation_id → S3 Object Lock | 🟡 stdout xong, cần boto3+bucket |
| `k8s_client.py` | Wrapper K8s (get state, restart/patch/rollout-undo + dry-run) | 🟡 stub, cần kubernetes lib |
| `snapshot.py` | CDO tự capture rollback snapshot trước execute | 🟡 urgent xong, deferred=git stub |
| `executors/urgent.py` | Path B — K8s API trực tiếp (dry-run rồi execute) | 🟡 wiring xong, call=stub |
| `executors/deferred.py` | Path A — Git commit → ArgoCD sync | 🔴 stub (cân nhắc designed-only) |
| `mock_ai_server.py` | Mock AI endpoint đúng schema — integrate trước khi có image AI | ✅ đầy đủ |

## Day-1 smoke test (offline, không cần cluster/AWS)

```bash
cd executor
pip install -r requirements.txt

# terminal 1: mock AI
python mock_ai_server.py

# terminal 2: chạy 1 scenario qua mock, K8s mock
CDO_K8S_MOCK=true AI_BASE_URL=http://127.0.0.1:8080 \
  python main.py scenarios/tc01_service_stuck.json
# → OUTCOME: auto_resolved, audit trail đầy đủ ra stdout

# safety gate unit test (8 case deny/allow)
python tests/test_safety_gate.py
```

## Lộ trình W12 (theo độ ưu tiên)

1. **MUST** — `k8s_client.py`: implement restart + patch_memory (server-side dry-run `dry_run="All"`). Bỏ comment `kubernetes` trong requirements. → TC-01..04 chạy thật trên EKS.
2. **MUST** — `audit.py` + `idempotency.py`: bỏ comment `boto3`, set `CDO_AUDIT_BUCKET` + `CDO_IDEMPOTENCY_TABLE` (Terraform module `audit/` đã tạo sẵn).
3. **MUST** — inject script + chạy ≥10 scenario / ≥4h → auto-resolve rate.
4. **SHOULD** — `executors/deferred.py`: Git→ArgoCD (TC-05/06/16). **Nếu thiếu thời gian → hạ queue/secret về designed-only.**
5. **SHOULD** — `_escalate`: Slack/mock pager + escalation_bundle.

## Lưu ý contract cần chốt trước W12 T1
- **SA namespace**: `CDO_EXECUTOR_NS` đang default `self-heal-system` theo contract §3.D. Nếu giữ `platform` phải có agreement văn bản với AI team.
- Không commit secret thật; không dùng static AWS key trong pod (IRSA).
