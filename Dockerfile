FROM node:20-alpine AS frontend-builder

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm config set fetch-retries 5 \
    && npm config set fetch-retry-factor 2 \
    && npm config set fetch-retry-mintimeout 2000 \
    && npm config set fetch-retry-maxtimeout 120000 \
    && npm ci

COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim AS backend-builder

WORKDIR /backend

ENV PYTHONUNBUFFERED=1

COPY backend/requirements.txt ./
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

COPY backend/ ./


FROM python:3.12-slim

WORKDIR /app

ARG APP_BUILD_VERSION=dev
ARG APP_BUILD_TAG=dev
ARG APP_BUILD_GIT_SHA=local
ARG APP_BUILD_TIME=

ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai
ENV APP_BUILD_VERSION=${APP_BUILD_VERSION}
ENV APP_BUILD_TAG=${APP_BUILD_TAG}
ENV APP_BUILD_GIT_SHA=${APP_BUILD_GIT_SHA}
ENV APP_BUILD_TIME=${APP_BUILD_TIME}

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl nginx tzdata \
    && ln -snf "/usr/share/zoneinfo/${TZ}" /etc/localtime \
    && echo "${TZ}" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

COPY --from=backend-builder /install /usr/local
COPY backend/ /app/
COPY --from=frontend-builder /frontend/dist /usr/share/nginx/html
COPY docker/all-in-one/nginx.conf /etc/nginx/nginx.conf
COPY docker/all-in-one/start.sh /start.sh

RUN chmod +x /start.sh \
    && mkdir -p /app/data /run/nginx /var/cache/nginx /var/log/nginx

LABEL org.opencontainers.image.version="${APP_BUILD_VERSION}" \
      org.opencontainers.image.revision="${APP_BUILD_GIT_SHA}" \
      org.opencontainers.image.created="${APP_BUILD_TIME}"

EXPOSE 5173 9008

CMD ["/start.sh"]
