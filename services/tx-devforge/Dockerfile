FROM python:3.12-slim
WORKDIR /app
COPY services/tx-devforge/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --retries 5 --timeout 120 -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
COPY shared/ ./shared/
COPY services/tx-devforge/src/ ./services/tx_devforge/src/
ENV PYTHONPATH=/app
EXPOSE 8017
CMD ["uvicorn", "services.tx_devforge.src.main:app", "--host", "0.0.0.0", "--port", "8017"]
