# CDO Self-Heal Executor — chạy trong namespace self-heal-system (hoặc platform)
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
# W12: bỏ comment kubernetes + boto3 trong requirements.txt trước khi build prod
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Executor là long-running controller; entrypoint mặc định chạy 1 scenario (override khi deploy).
# W12: thay bằng server mode (HTTP ingestion / SQS consumer) — xem TODO main.py.
ENTRYPOINT ["python", "main.py"]
