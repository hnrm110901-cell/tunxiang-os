FROM python:3.12-slim
WORKDIR /app
COPY services/tx-devforge/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --retries 5 --timeout 120 -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
COPY shared/ ./shared/
COPY services/tx-devforge/src/ ./services/tx_devforge/src/
ENV PYTHONPATH=/app
# Trivy DS-0002：以非 root 用户运行 FastAPI，降低进程被入侵后的横向风险
RUN useradd --system --no-create-home --shell /usr/sbin/nologin --uid 1001 txuser \
 && chown -R txuser:txuser /app
USER txuser
EXPOSE 8017
CMD ["uvicorn", "services.tx_devforge.src.main:app", "--host", "0.0.0.0", "--port", "8017"]
