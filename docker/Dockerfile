# syntax=docker/dockerfile:1.7
# One image recipe, two targets:  --target api  |  --target worker
FROM python:3.15-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY apps/api ./apps/api
RUN pip install ".[api,azure,pdf]"
# Optional: bake a demo risk model into the image (local docker-compose). In Azure the bundle is downloaded from Blob Storage.
ARG TRAIN_DEMO_MODEL=false
RUN if [ "$TRAIN_DEMO_MODEL" = "true" ]; then claimlens train --n 3000; fi
RUN useradd --create-home --uid 10001 claimlens && mkdir -p /data && chown -R claimlens /data /app
USER 10001
ENV CLAIMLENS_DATA_DIR=/data CLAIMLENS_MODEL_DIR=/app/models

FROM base AS api
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"
CMD ["uvicorn", "claimlens_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

FROM base AS worker
CMD ["claimlens", "worker"]
