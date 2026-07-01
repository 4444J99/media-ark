# Container for the media-ark stdlib HTTP API + dashboard on Cloud Run.
# The engine is dependency-free, so this is just a Python base over the source
# tree -- no requirements install, matching the zero-dependency ethos.
#
# The API server also serves the static dashboard (web/) via _serve_static, so
# this single service is a complete product surface (API + UI).
FROM python:3.11-slim

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

# Cloud Run injects $PORT (default 8080); listen on all interfaces.
EXPOSE 8080
CMD ["sh", "-c", "exec python -m src.platform.api_server --host 0.0.0.0 --port ${PORT:-8080}"]
