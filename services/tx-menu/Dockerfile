FROM python:3.11-slim
WORKDIR /app
COPY services/tx-menu/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ ./shared/
COPY services/tx-menu/src/ ./services/tx-menu/src/
ENV PYTHONPATH=/app
CMD ["uvicorn", "services.tx-menu.src.main:app", "--host", "0.0.0.0", "--port", "8002"]
