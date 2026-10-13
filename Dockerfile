# One container: FastAPI (API + built web app). Phase 2 adds the Baileys process alongside.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
COPY --from=web /web/dist /app/web/dist
ENV PADDY_DB=/data/paddy.db
VOLUME /data
EXPOSE 8000
# Trust X-Forwarded-* only from FORWARDED_ALLOW_IPS (VPN range, set in docker-compose.yml).
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
