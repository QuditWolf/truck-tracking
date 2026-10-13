# One container: FastAPI (API + built web app) and the Baileys WhatsApp bridge.

FROM node:22-slim AS web
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM node:22-slim AS wa
WORKDIR /wa
COPY wa/package*.json ./
RUN npm ci --omit=dev

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
COPY --from=web /web/dist /app/web/dist
COPY --from=wa /wa/node_modules /app/wa/node_modules
COPY wa/package.json wa/index.js /app/wa/
COPY deploy/start.sh /app/start.sh
ENV PADDY_DB=/data/paddy.db WA_SESSION_DIR=/data/wa_session API_URL=http://127.0.0.1:8000
VOLUME /data
EXPOSE 8000
# Trust X-Forwarded-* only from FORWARDED_ALLOW_IPS (VPN range, set in docker-compose.yml).
CMD ["/app/start.sh"]
