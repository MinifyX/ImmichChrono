# syntax=docker/dockerfile:1.7

# --- Frontend (built once on the build host, architecture-independent output) ---
FROM --platform=$BUILDPLATFORM node:24-slim AS web
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH
RUN corepack enable
WORKDIR /web
COPY web/package.json web/pnpm-lock.yaml ./
RUN --mount=type=cache,id=pnpm,target=/pnpm/store pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

# --- Backend dependencies ---
FROM python:3.13-slim AS deps
WORKDIR /app
COPY backend/pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/pip \
    mkdir immichchrono && touch immichchrono/__init__.py && \
    pip install --prefix=/install . && rm -rf /install/lib/python*/site-packages/immichchrono*

# --- Runtime ---
FROM python:3.13-slim
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && apt-get install -y --no-install-recommends libimage-exiftool-perl
COPY --from=deps /install /usr/local
RUN useradd --system --uid 1000 --home-dir /app chrono && install -d -o chrono -g chrono /data
WORKDIR /app
COPY backend/immichchrono ./immichchrono
COPY --from=web /web/build ./static
# FORWARDED_ALLOW_IPS: address of the reverse proxy whose X-Forwarded-* headers are trusted.
ENV PYTHONUNBUFFERED=1 DATA_DIR=/data STATIC_DIR=/app/static FORWARDED_ALLOW_IPS=127.0.0.1
USER chrono
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1
CMD ["uvicorn", "immichchrono.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
