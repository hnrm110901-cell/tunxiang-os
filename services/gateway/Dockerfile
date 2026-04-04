FROM python:3.11-slim
WORKDIR /app
COPY services/gateway/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    -r requirements.txt
COPY shared/ ./shared/
COPY services/gateway/src/ ./services/gateway/src/
ENV PYTHONPATH=/app
CMD ["uvicorn", "services.gateway.src.main:app", "--host", "0.0.0.0", "--port", "8000"]
