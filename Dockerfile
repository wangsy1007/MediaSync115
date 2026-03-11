FROM --platform=linux/amd64,linux/arm64 node:20-alpine AS frontend-builder

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm config set fetch-retries 5 \
    && npm config set fetch-retry-factor 2 \
    && npm config set fetch-retry-mintimeout 2000 \
    && npm config set fetch-retry-maxtimeout 120000 \
    && npm ci

COPY frontend/ ./
RUN npm run build


FROM --platform=linux/amd64,linux/arm64 python:3.12-slim AS backend-builder

WORKDIR /backend

ENV PYTHONUNBUFFERED=1

COPY backend/requirements.txt ./
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

COPY backend/ ./


FROM --platform=linux/amd64,linux/arm64 python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates nginx \
    && rm -rf /var/lib/apt/lists/*

COPY --from=backend-builder /install /usr/local
COPY backend/ /app/
COPY --from=frontend-builder /frontend/dist /usr/share/nginx/html
COPY docker/all-in-one/nginx.conf /etc/nginx/nginx.conf
COPY docker/all-in-one/start.sh /start.sh

RUN chmod +x /start.sh \
    && mkdir -p /app/data /run/nginx /var/cache/nginx /var/log/nginx

EXPOSE 80

CMD ["/start.sh"]
