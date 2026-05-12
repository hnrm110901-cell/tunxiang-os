FROM python:3.12-slim AS builder

WORKDIR /app

# 安装构建依赖，完成后清理缓存
COPY services/tx-brain/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --user \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    -r requirements.txt


FROM python:3.12-slim

WORKDIR /app

# 从 builder 阶段复制已安装的包
COPY --from=builder /root/.local /root/.local

# 复制 shared 层（Ontology 实体 + 事件定义等）
COPY shared/ ./shared/

# 复制 tx-brain 业务代码
COPY services/tx-brain/src/ ./src/

# 将 pip --user 安装路径加入 PATH
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/app

# F#2 PR-2: 以非 root 用户运行（PR #444 Helm 已 enforce runAsUser:10001）
# UID 10001 与 CSO 2026-05-11 Option A 对齐
RUN useradd --uid 10001 --no-create-home --shell /sbin/nologin app \
 && chmod -R go+rX /root/.local
USER 10001

EXPOSE 8010

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8010"]
