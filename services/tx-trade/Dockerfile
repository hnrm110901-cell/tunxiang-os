FROM python:3.11-slim
WORKDIR /app
COPY services/tx-trade/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ ./shared/
COPY services/tx-trade/src/ ./services/tx-trade/src/
ENV PYTHONPATH=/app
CMD ["uvicorn", "services.tx-trade.src.main:app", "--host", "0.0.0.0", "--port", "8001"]
