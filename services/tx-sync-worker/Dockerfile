FROM python:3.11-slim
WORKDIR /app
ENV TZ=Asia/Shanghai
COPY services/tx-sync-worker/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    -r requirements.txt
COPY shared/ ./shared/
# 跨服务 import: gateway.wecom_group_service / models / database
# Phase 1 临时方案 (per plan §7.6); Phase 2 follow-up 拆 shared/wecom/
COPY services/gateway/ ./services/gateway/
COPY services/tx-sync-worker/src/ ./services/tx_sync_worker/src/
ENV PYTHONPATH=/app
# F#2: 以非 root 用户运行 (Helm runAsUser:10001, 与 tx-event-relay 一致)
RUN useradd --uid 10001 --no-create-home --shell /sbin/nologin app
USER 10001
CMD ["uvicorn", "services.tx_sync_worker.src.main:app", "--host", "0.0.0.0", "--port", "8021"]
