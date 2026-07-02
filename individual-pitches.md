# Individual Pitches — TF3 CDO-02

> Mỗi thành viên chuẩn bị pitch cá nhân + individual defense (panel hỏi riêng từng người).
> Mỗi người: vai trò · phần mình sở hữu · quyết định kiến trúc mình đưa ra (WHY) · demo mình chủ trì · câu hỏi phòng thủ hay bị hỏi.
> Điền theo phân vai thực tế trong `Role.md`.

---

## Thành viên 1 — <Tên> (PM + Tech Lead)

- **Sở hữu:** kiến trúc tổng thể, executor self-heal loop, safety gate, IaC, deploy live, integrate AI engine.
- **Quyết định chính (WHY):**
  - K8s-heavy orchestration thay vì serverless (ADR-001) — sát bài self-heal K8s.
  - AI = decide / CDO = execute boundary (ADR-002) — AI không chạm K8s API.
  - Executor tự kéo dense-window Prometheus — ML cần chuỗi metric dày, SQS chỉ là trigger.
- **Demo chủ trì:** E2E self-heal, safety 3 lớp, audit ([11_demo_guide.md](docs/11_demo_guide.md)).
- **Q&A phòng thủ:** _<TODO: vì sao GOVERNANCE thay COMPLIANCE; vì sao deferred để stub; dense-window vs signal rời>_

## Thành viên 2 — <Tên> (<vai trò>)

- **Sở hữu:** _<TODO theo Role.md>_
- **Quyết định chính (WHY):** _<TODO>_
- **Demo chủ trì:** _<TODO>_
- **Q&A phòng thủ:** _<TODO>_

## Thành viên 3 — <Tên> (<vai trò>)

- **Sở hữu:** _<TODO>_
- **Quyết định chính (WHY):** _<TODO>_
- **Demo chủ trì:** _<TODO>_
- **Q&A phòng thủ:** _<TODO>_

---

> Mẹo: mỗi người nắm CHẮC phần mình + biết 1 câu về phần người khác (tránh "không biết, đó là phần bạn kia"). Xem điểm mạnh/gap hệ thống trong [docs/10_w12_status_and_demo.md](docs/10_w12_status_and_demo.md).
