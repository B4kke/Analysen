FROM python:3.12-slim AS research-dependencies
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.lock requirements-research.lock ./
# The research lock is compiled from requirements.txt and includes the base
# pins plus the crawler/document stack. Keep the base lock copied as a
# separately auditable input, but install one coherent resolved set.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        default-jre-headless \
        tesseract-ocr tesseract-ocr-nor \
        build-essential pkg-config libicu-dev \
    && rm -rf /var/lib/apt/lists/*
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements-research.lock \
    && playwright install --with-deps chromium
FROM research-dependencies AS runtime
COPY . .
CMD ["uvicorn", "apps.api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
