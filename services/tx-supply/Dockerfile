FROM python:3.11-slim
WORKDIR /app
COPY services/tx-supply/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --retries 5 --timeout 120 -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
COPY shared/ ./shared/
COPY services/tx-supply/src/ ./services/tx_supply/src/
ENV PYTHONPATH=/app
# F#2 PR-2: 以非 root 用户运行（PR #444 Helm 已 enforce runAsUser:10001）
RUN useradd --uid 10001 --no-create-home --shell /sbin/nologin app
USER 10001
CMD ["uvicorn", "services.tx_supply.src.main:app", "--host", "0.0.0.0", "--port", "8006"]
