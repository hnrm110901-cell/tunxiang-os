FROM python:3.12-slim
WORKDIR /app
COPY services/tx-devforge/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --retries 5 --timeout 120 -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
COPY shared/ ./shared/
COPY services/tx-devforge/src/ ./services/tx_devforge/src/
ENV PYTHONPATH=/app
# F#2 PR-2: 以非 root 用户运行（PR #444 Helm 已 enforce runAsUser:10001）
# UID 10001 与 CSO 2026-05-11 Option A 对齐（原 1001 偏离 Helm chart 值）
RUN useradd --uid 10001 --no-create-home --shell /sbin/nologin app \
 && chown -R 10001:10001 /app
USER 10001
EXPOSE 8017
CMD ["uvicorn", "services.tx_devforge.src.main:app", "--host", "0.0.0.0", "--port", "8017"]
