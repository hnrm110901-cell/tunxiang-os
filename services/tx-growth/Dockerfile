FROM python:3.11-slim
WORKDIR /app
COPY services/tx-growth/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --retries 5 --timeout 120 -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
COPY shared/ ./shared/
COPY services/tx-growth/src/ ./services/tx_growth/src/
ENV PYTHONPATH=/app
CMD ["uvicorn", "services.tx_growth.src.main:app", "--host", "0.0.0.0", "--port", "8004"]
