FROM python:3.11-slim
WORKDIR /app
COPY services/tx-trade/requirements.txt ./requirements.txt
# requirements.lock（精确锁定版本，由 scripts/generate_requirements_locks.sh 生成）
# 若已生成：将下行 COPY 注释取消，并将 RUN 中 requirements.txt 替换为 requirements.lock
# COPY services/tx-trade/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    -r requirements.txt
COPY shared/ ./shared/
COPY services/tx-trade/src/ ./services/tx_trade/src/
COPY services/tx-org/src/services/permission_service.py ./services/permission_service.py
ENV PYTHONPATH=/app
CMD ["uvicorn", "services.tx_trade.src.main:app", "--host", "0.0.0.0", "--port", "8001"]
