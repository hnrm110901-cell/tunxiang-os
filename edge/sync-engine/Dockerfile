FROM python:3.12-slim AS builder

WORKDIR /app

# 安装依赖（无 requirements.txt，手动指定）
RUN pip install --no-cache-dir --user \
    asyncpg \
    aiohttp \
    structlog \
    python-dotenv \
    pydantic-settings


FROM python:3.12-slim

WORKDIR /app

# 从 builder 阶段复制已安装的包
COPY --from=builder /root/.local /root/.local

# 复制边缘同步引擎所有源文件（从项目根目录 context 复制）
COPY edge/sync-engine/main.py ./main.py
COPY edge/sync-engine/config.py ./config.py
COPY edge/sync-engine/sync_engine.py ./sync_engine.py
COPY edge/sync-engine/conflict_resolver.py ./conflict_resolver.py
COPY edge/sync-engine/models.py ./models.py
COPY edge/sync-engine/sync_tracker.py ./sync_tracker.py
COPY edge/sync-engine/offline_sync_service.py ./offline_sync_service.py
COPY edge/sync-engine/sync_routes.py ./sync_routes.py

# 将 pip --user 安装路径加入 PATH
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/app

# 创建非 root 用户运行（等保合规）
RUN addgroup --system txuser && adduser --system --ingroup txuser txuser
USER txuser

CMD ["python", "main.py"]
