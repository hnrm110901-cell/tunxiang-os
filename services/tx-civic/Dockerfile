FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONPATH=/app/src:/app/../../shared
EXPOSE 8014
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8014"]
