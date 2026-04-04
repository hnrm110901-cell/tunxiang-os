FROM python:3.11-slim
WORKDIR /app
COPY services/tx-intel/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --retries 5 --timeout 120 -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
COPY shared/ ./shared/
COPY services/tx-intel/src/ ./services/tx_intel/src/
ENV PYTHONPATH=/app
CMD ["uvicorn", "services.tx_intel.src.main:app", "--host", "0.0.0.0", "--port", "8011"]
