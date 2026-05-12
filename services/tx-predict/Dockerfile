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

# F#2 PR-2: 以非 root 用户运行（PR #444 Helm 已 enforce runAsUser:10001）
# UID 10001 与 CSO 2026-05-11 Option A 对齐
RUN useradd --uid 10001 --no-create-home --shell /sbin/nologin app \
 && chmod -R go+rX /root/.local
USER 10001

EXPOSE 8013

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8013"]
