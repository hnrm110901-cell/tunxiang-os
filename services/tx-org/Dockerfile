FROM python:3.11-slim
WORKDIR /app
COPY services/tx-org/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --retries 5 --timeout 120 -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
COPY shared/ ./shared/
COPY services/tx-org/src/ ./services/tx_org/src/
ENV PYTHONPATH=/app
CMD ["uvicorn", "services.tx_org.src.main:app", "--host", "0.0.0.0", "--port", "8012"]
