# Telemetry and Observability - Folder Structure

File này giải thích ngắn cấu trúc thư mục `Telemetry_and_Observability`.

## Cấu trúc chính

```text
Telemetry_and_Observability/
  IaC_Observability_v1.0.md
  Prometheus_v1.0.md
  picture/
  TeamC_Telemetry_customer/
```

## Ý nghĩa từng phần

| Thư mục/File | Ý nghĩa |
|---|---|
| `IaC_Observability_v1.0.md` | Ghi chú/hướng dẫn phần Infrastructure as Code cho observability |
| `Prometheus_v1.0.md` | Ghi chú/hướng dẫn phần Prometheus |
| `picture/` | Hình ảnh, sơ đồ liên quan observability |
| `TeamC_Telemetry_customer/` | Phần Team C bàn giao cho custom telemetry |

## Cấu trúc TeamC_Telemetry_customer

```text
TeamC_Telemetry_customer/
  custom_telemetry/
  evidence/
```

| Thư mục | Ý nghĩa |
|---|---|
| `custom_telemetry/` | Code và tài liệu adapter normalize raw telemetry sang `telemetry_window[]` đúng contract new 4 |
| `evidence/` | Bằng chứng test: raw input, output normalized, validate result, executor stdout, scenario mock |

## Luồng bàn giao Team C

```text
raw telemetry JSON
  -> custom_telemetry
  -> telemetry_window[]
  -> executor/main.py hoặc telemetry forwarder
  -> AI Engine /v1/detect
```

Team C chỉ chịu trách nhiệm phần normalize telemetry và evidence. Team deploy/platform chịu trách nhiệm đóng gói container, worker/pod, queue, retry, DLQ và routing sang AI Engine.
