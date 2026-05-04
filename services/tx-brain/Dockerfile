FROM python:3.12-slim

WORKDIR /app

COPY services/tx-brain/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    -r requirements.txt

COPY shared/ ./shared/
COPY services/tx-brain/src/ ./src/

ENV PYTHONPATH=/app

EXPOSE 8010

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8010"]
