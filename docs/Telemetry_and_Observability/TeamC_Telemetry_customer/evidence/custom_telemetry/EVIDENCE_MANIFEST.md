# Custom Telemetry Evidence Manifest

## Scope

Evidence này chứng minh Team C custom telemetry adapter có thể:

- Nhận mock scenario JSON và raw telemetry sample JSON.
- Normalize thành `telemetry_window[]` đúng contract new 4.
- Validate output contract.
- Scrub secret/PII trong log.
- Chạy được qua executor mock flow với AI mock.

## Files

| File | Ý nghĩa |
|---|---|
| `tf3_executor_scenarios/` | Bản copy toàn bộ scenario mock/offline từ `TF3-Self-Heal-Agent-AWS/executor/scenarios/*.json` dùng để test adapter |
| `raw_input_mock_scenario_sc01.json` | Scenario mock gốc từ TF3 executor |
| `output_mock_scenario_sc01_contract.json` | Scenario sau normalize, giữ wrapper scenario |
| `telemetry_window_mock_scenario_sc01.json` | Chỉ phần `telemetry_window[]` sau normalize |
| `validate_mock_scenario_sc01.json` | Kết quả validate scenario normalized |
| `raw_input_log_sample.json` | Raw log sample có token/password/email |
| `telemetry_window_log_sample.json` | Log sample sau normalize thành `application_log_event` và redact secret/PII |
| `validate_log_sample.json` | Kết quả validate log telemetry |
| `raw_input_trace_span_sample.json` | Raw trace/span sample lỗi |
| `telemetry_window_trace_span_sample.json` | Trace sample sau normalize thành `distributed_trace_error_event` |
| `validate_trace_span_sample.json` | Kết quả validate trace telemetry |
| `executor_stdout_sc01.jsonl` | Stdout executor khi chạy scenario normalized qua mock AI |

## Expected Results

Validate files phải có dạng:

```json
{
  "valid": true,
  "points": 1
}
```

`telemetry_window_log_sample.json` phải normalize được log sample thành `application_log_event`:

```text
checkout failed credential placeholder_token secret placeholder_password user user-at-example.test
```

`executor_stdout_sc01.jsonl` phải kết thúc bằng:

```text
>>> OUTCOME: auto_resolved
```
