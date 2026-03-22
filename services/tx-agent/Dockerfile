FROM python:3.11-slim
WORKDIR /app
COPY services/tx-agent/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || pip install --no-cache-dir fastapi uvicorn structlog
COPY shared/ ./shared/
COPY services/tx-agent/src/ ./services/tx-agent/src/
ENV PYTHONPATH=/app
CMD ["uvicorn", "services.tx-agent.src.main:app", "--host", "0.0.0.0", "--port", "8008"]
