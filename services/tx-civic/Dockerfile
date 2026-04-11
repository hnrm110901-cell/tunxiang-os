FROM python:3.12-slim
WORKDIR /app
COPY services/tx-civic/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --retries 5 --timeout 120 -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
COPY shared/ ./shared/
COPY services/tx-civic/src/ ./services/tx_civic/src/
ENV PYTHONPATH=/app
EXPOSE 8014
CMD ["uvicorn", "services.tx_civic.src.main:app", "--host", "0.0.0.0", "--port", "8014"]
