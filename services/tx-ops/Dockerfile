FROM python:3.11-slim
WORKDIR /app
COPY services/tx-ops/requirements.txt ./requirements.txt
# requirements.lock（精确锁定版本，由 scripts/generate_requirements_locks.sh 生成）
# 若已生成：将下行 COPY 注释取消，并将 RUN 中 requirements.txt 替换为 requirements.lock
# COPY services/tx-ops/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --retries 5 --timeout 120 -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
COPY shared/ ./shared/
COPY services/tx-ops/src/ ./services/tx_ops/src/
ENV PYTHONPATH=/app
CMD ["uvicorn", "services.tx_ops.src.main:app", "--host", "0.0.0.0", "--port", "8005"]
