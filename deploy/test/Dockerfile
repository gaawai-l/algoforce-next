FROM node:24-bookworm-slim AS frontend
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates python3
WORKDIR /build
COPY integrations/wealthfolio/upstream.json /config/upstream.json
RUN git clone --depth 1 --branch v3.8.0 https://github.com/wealthfolio/wealthfolio.git host && \
    test "$(git -C host rev-parse HEAD)" = "8f6f9898d30e84d7215e01d3d06cd65e02c9ab1b"
COPY integrations/wealthfolio/patches/ /patches/
RUN git -C host apply /patches/*.patch
COPY integrations/wealthfolio/overlay/ host/
WORKDIR /build/host
RUN npm install -g pnpm@10.33.4 && pnpm install --frozen-lockfile
RUN pnpm build:types && pnpm build

FROM node:24-bookworm-slim AS wallet-build
WORKDIR /app
COPY services/wallet-auth/package*.json ./
RUN npm ci --ignore-scripts
COPY services/wallet-auth/ ./
ARG VITE_WALLETCONNECT_PROJECT_ID
RUN npm run build

FROM node:24-bookworm-slim AS wallet-auth
WORKDIR /app
COPY --from=wallet-build /app/package*.json ./
RUN npm ci --omit=dev --ignore-scripts && mkdir -p /data && chown node:node /data
COPY services/wallet-auth/src/auth.mjs services/wallet-auth/src/server.mjs ./src/
USER node
EXPOSE 8790
CMD ["node", "src/server.mjs"]

FROM nginx:1.28-alpine AS web
COPY --from=frontend /build/host/dist /usr/share/nginx/html
COPY --from=wallet-build /app/dist /usr/share/nginx/html/login
COPY deploy/test/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80

FROM python:3.14-slim AS analytics
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 WHEELHOUSE_DATA_DIR=/data WHEELHOUSE_DEPLOYMENT=test
WORKDIR /app
COPY services/analytics/ /app/services/analytics/
RUN pip install --no-cache-dir setuptools==80.9.0 wheel==0.45.1 && \
    pip install --no-cache-dir -r /app/services/analytics/requirements.lock && \
    pip install --no-cache-dir --no-build-isolation --no-deps /app/services/analytics && \
    groupadd -g 1000 analytics && useradd -u 1000 -g analytics -M analytics && \
    mkdir -p /data && chown analytics:analytics /data
COPY deploy/test/application.py /app/application.py
USER 1000:1000
EXPOSE 8787
CMD ["uvicorn", "application:app", "--host", "0.0.0.0", "--port", "8787", "--no-access-log"]
