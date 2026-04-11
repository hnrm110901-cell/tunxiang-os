FROM python:3.11-slim
WORKDIR /app
COPY services/tx-pay/pyproject.toml ./pyproject.toml
RUN pip install --no-cache-dir --retries 5 --timeout 120 -i https://mirrors.aliyun.com/pypi/simple/ \
    fastapi uvicorn sqlalchemy[asyncio] asyncpg pydantic structlog httpx cryptography
COPY shared/ ./shared/
COPY services/tx-pay/src/ ./services/tx_pay/src/
ENV PYTHONPATH=/app
CMD ["uvicorn", "services.tx_pay.src.main:app", "--host", "0.0.0.0", "--port", "8013"]
