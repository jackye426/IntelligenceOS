# Monorepo build: set Railway Root Directory to repo root (.) and Dockerfile path to data-worker/Dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY marketing-pipeline /app/marketing-pipeline
RUN pip install --no-cache-dir -e "/app/marketing-pipeline[media]"

COPY data-worker /app/data-worker
WORKDIR /app/data-worker
RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "main.py"]
