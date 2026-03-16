#!/usr/bin/env bash
set -Eeuo pipefail

shutdown() {
  if [[ -n "${uvicorn_pid:-}" ]]; then
    kill -TERM "${uvicorn_pid}" 2>/dev/null || true
  fi
  if [[ -n "${nginx_pid:-}" ]]; then
    kill -TERM "${nginx_pid}" 2>/dev/null || true
  fi
}

trap shutdown SIGINT SIGTERM

nginx -t

uvicorn main:app --host 127.0.0.1 --port 8000 --lifespan off &
uvicorn_pid=$!

nginx -g 'daemon off;' &
nginx_pid=$!

wait -n "${uvicorn_pid}" "${nginx_pid}"
exit_code=$?

shutdown

wait "${uvicorn_pid}" 2>/dev/null || true
wait "${nginx_pid}" 2>/dev/null || true

exit "${exit_code}"
