# Container for the media-ark stdlib HTTP API + dashboard.
# Deploy target is Cloudflare Containers (derived from the live stack; see
# DEPLOY.md) -- the image is host-agnostic and also runs on Cloud Run.
# The Python engine is dependency-free (no pip install), but the ingest
# pipeline shells out to the `tesseract` OCR binary (src/media_ark/
# process_captures.py: gracefully skipped when absent). Installing it here
# turns OCR on in the container instead of silently no-opping.
#
# The API server also serves the static dashboard (web/) via _serve_static, so
# this single service is a complete product surface (API + UI).
FROM python:3.11-slim

# System OCR binary (not a Python dep) -- enables the tesseract branch of the
# capture pipeline. --no-install-recommends keeps the slim image lean.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# PYTHONPATH=src is the exact layout the test matrix runs under: the brand
# module resolves at src/media_ark and the platform package at src/platform
# (whose __init__ pins the real stdlib `platform`, avoiding the shadow).
ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    MEDIA_ARK_QUOTA_DB=/tmp/media-ark/quota.json \
    MEDIA_ARK_USERS_DB=/tmp/media-ark/users.db \
    MEDIA_ARK_USER_SANDBOX_ROOT=/tmp/media-ark/sandboxes

# The host injects $PORT (Cloudflare Containers / Cloud Run both do; default
# 8080); listen on all interfaces.
EXPOSE 8080
CMD ["sh", "-c", "exec python -m src.platform.api_server --host 0.0.0.0 --port ${PORT:-8080}"]
