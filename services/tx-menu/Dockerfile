FROM python:3.11-slim
WORKDIR /app
COPY services/tx-menu/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    -r requirements.txt
COPY shared/ ./shared/
COPY services/tx-menu/src/ ./services/tx_menu/src/
ENV PYTHONPATH=/app
CMD ["uvicorn", "services.tx_menu.src.main:app", "--host", "0.0.0.0", "--port", "8002"]
