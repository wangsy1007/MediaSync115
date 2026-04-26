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

echo "Starting nginx..."
nginx -g 'daemon off;' &
nginx_pid=$!

echo "Starting backend..."
uvicorn main:app --host 127.0.0.1 --port 8000 &
uvicorn_pid=$!

wait_for_backend() {
  echo "Waiting for backend to become ready..."
  local max_wait=300
  local elapsed=0

  while [ "${elapsed}" -lt "${max_wait}" ]; do
    if curl -sf --max-time 2 http://127.0.0.1:8000/health >/dev/null 2>&1; then
      echo "Backend is ready (${elapsed}s)."
      return 0
    fi
    if ! kill -0 "${uvicorn_pid}" 2>/dev/null; then
      echo "Backend process exited unexpectedly while waiting for readiness"
      return 1
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done

  echo "Backend did not become ready within ${max_wait}s."
  return 1
}

if ! wait_for_backend; then
  shutdown
  wait "${uvicorn_pid}" 2>/dev/null || true
  wait "${nginx_pid}" 2>/dev/null || true
  exit 1
fi

wait -n "${uvicorn_pid}" "${nginx_pid}"
exit_code=$?

shutdown

wait "${uvicorn_pid}" 2>/dev/null || true
wait "${nginx_pid}" 2>/dev/null || true

exit "${exit_code}"
