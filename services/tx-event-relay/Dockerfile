FROM python:3.11-slim
WORKDIR /app
COPY services/tx-event-relay/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    -r requirements.txt
COPY shared/ ./shared/
COPY services/tx-event-relay/src/ ./services/tx_event_relay/src/
ENV PYTHONPATH=/app
# F#2 PR-2: 以非 root 用户运行 (Helm runAsUser:10001)
RUN useradd --uid 10001 --no-create-home --shell /sbin/nologin app
USER 10001
CMD ["uvicorn", "services.tx_event_relay.src.main:app", "--host", "0.0.0.0", "--port", "8020"]
