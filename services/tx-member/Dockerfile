FROM python:3.11-slim
WORKDIR /app
COPY services/tx-member/requirements.txt ./requirements.txt
# requirements.lock（精确锁定版本，由 scripts/generate_requirements_locks.sh 生成）
# 若已生成：将下行 COPY 注释取消，并将 RUN 中 requirements.txt 替换为 requirements.lock
# COPY services/tx-member/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --retries 5 --timeout 120 -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
COPY shared/ ./shared/
COPY services/tx-member/src/ ./services/tx_member/src/
ENV PYTHONPATH=/app
# F#2 PR-2: 以非 root 用户运行（PR #444 Helm 已 enforce runAsUser:10001）
RUN useradd --uid 10001 --no-create-home --shell /sbin/nologin app
USER 10001
CMD ["uvicorn", "services.tx_member.src.main:app", "--host", "0.0.0.0", "--port", "8003"]
