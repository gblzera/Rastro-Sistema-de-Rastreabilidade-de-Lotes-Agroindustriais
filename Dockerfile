FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RASTRO_WEB_DIR=/app/web

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY rastro ./rastro
COPY web ./web

# O grafo vive em memória: a aplicação roda com um único processo.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn rastro.api.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
