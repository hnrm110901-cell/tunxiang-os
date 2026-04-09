FROM python:3.12-slim AS builder

WORKDIR /app

COPY services/tx-predict/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --user \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    -r requirements.txt


FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /root/.local /root/.local
COPY shared/ ./shared/
COPY services/tx-predict/src/ ./src/

ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/app

RUN addgroup --system txuser && adduser --system --ingroup txuser txuser
USER txuser

EXPOSE 8013

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8013"]
