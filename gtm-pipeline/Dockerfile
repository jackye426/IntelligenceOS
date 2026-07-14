# Playwright + Chromium for Doctify scrapes on Railway.
# Pin image tag to the playwright package major/minor used in pyproject.
FROM mcr.microsoft.com/playwright/python:v1.52.0-jammy

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    GTM_DATA_DIR=/tmp/gtm-data

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[service]"

EXPOSE 8080

CMD ["sh", "-c", "uvicorn gtm_pipeline.service:app --host 0.0.0.0 --port ${PORT:-8080}"]
