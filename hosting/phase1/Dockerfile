# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.9.11-python3.12-bookworm-slim
WORKDIR /app/server
COPY server/pyproject.toml server/uv.lock ./
COPY server/src ./src
RUN --mount=type=secret,id=ca_bundle \
    if [ -f /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    uv sync --frozen --no-dev --no-editable
COPY content /app/content
RUN useradd --uid 10001 --create-home worldshard && mkdir -p /app/data && chown -R worldshard:worldshard /app
USER worldshard
ENV WORLDFORGE_ENV=production WORLDFORGE_DB=/app/data/world.db WORLDFORGE_CONTENT_DIR=/app/content
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD ["/app/server/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4)"]
CMD ["/app/server/.venv/bin/uvicorn", "worldforge.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--ws-max-size", "65536", "--forwarded-allow-ips", "*"]
