# Alert Forwarder — Alertmanager webhook → SQS (telemetry-contract §2.5.C)
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alert_map.py forwarder.py scrub.py ./

# Chạy non-root (đồng nhất securityContext manifest)
RUN useradd -u 10001 -m appuser
USER 10001

EXPOSE 8080
CMD ["python", "forwarder.py"]
