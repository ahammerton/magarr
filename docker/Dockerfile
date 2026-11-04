# syntax=docker/dockerfile:1

# ---- Frontend build (runs on the build host's arch; output is arch-independent) ----
FROM --platform=$BUILDPLATFORM node:22-alpine AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Runtime ----
FROM python:3.12-slim AS runtime

ARG VERSION=dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="Magarr" \
      org.opencontainers.image.description="Self-hosted magazine PVR for Usenet and BitTorrent" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.licenses="GPL-3.0-only"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MAGARR_DOCKER=1 \
    MAGARR_CONFIG_DIR=/config \
    MAGARR_FRONTEND_DIR=/app/frontend

WORKDIR /app
COPY backend/pyproject.toml /app/backend/
COPY backend/magarr /app/backend/magarr
RUN pip install /app/backend

COPY --from=frontend /src/frontend/dist /app/frontend

RUN useradd --system --uid 1000 --home-dir /config magarr \
    && mkdir -p /config /magazines \
    && chown magarr:magarr /config /magazines
USER magarr

VOLUME ["/config", "/magazines"]
EXPOSE 8282

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8282/health', timeout=4).status == 200 else 1)"

CMD ["magarr"]
