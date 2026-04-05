FROM python:3.11-slim
WORKDIR /app
COPY services/tx-trade/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    -r requirements.txt
COPY shared/ ./shared/
COPY services/tx-trade/src/ ./services/tx_trade/src/
COPY services/tx-org/src/services/permission_service.py ./services/permission_service.py
ENV PYTHONPATH=/app
CMD ["uvicorn", "services.tx_trade.src.main:app", "--host", "0.0.0.0", "--port", "8001"]
