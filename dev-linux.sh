#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

BACKEND_PID_FILE="$BACKEND_DIR/backend.dev.pid"
FRONTEND_PID_FILE="$FRONTEND_DIR/frontend.dev.pid"
BACKEND_LOG_FILE="$BACKEND_DIR/backend.dev.log"
FRONTEND_LOG_FILE="$FRONTEND_DIR/frontend.dev.log"
BACKEND_PATTERN="uvicorn main:app --host 127\\.0\\.0\\.1 --port 8000"
FRONTEND_PATTERN="vite(\\.js)? .*--host 127\\.0\\.0\\.1 --port 5173"

BACKEND_CMD="./.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000"
FRONTEND_CMD="./node_modules/.bin/vite --host 127.0.0.1 --port 5173"

usage() {
  cat <<'EOF'
Usage: ./dev-linux.sh <command>

Commands:
  start    Start backend and frontend in the background
  stop     Stop backend and frontend
  restart  Restart backend and frontend
  status   Show process and HTTP status
  logs     Tail backend and frontend logs
EOF
}

is_running() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
  fi
  return 1
}

find_pid_by_pattern() {
  local pattern="$1"
  ps -eo pid=,args= | awk -v pat="$pattern" '$0 ~ pat {print $1; exit}'
}

refresh_pid_file() {
  local pid_file="$1"
  local pattern="$2"

  if is_running "$pid_file"; then
    return 0
  fi

  local pid
  pid="$(find_pid_by_pattern "$pattern")"
  if [[ -n "$pid" ]]; then
    echo "$pid" > "$pid_file"
    return 0
  fi

  if [[ -f "$pid_file" ]]; then
    rm -f "$pid_file"
  fi

  return 1
}

start_service() {
  local name="$1"
  local workdir="$2"
  local pid_file="$3"
  local log_file="$4"
  local cmd="$5"
  local pattern="$6"

  refresh_pid_file "$pid_file" "$pattern" || true

  if is_running "$pid_file"; then
    echo "$name already running: pid $(cat "$pid_file")"
    return 0
  fi

  mkdir -p "$(dirname "$log_file")"
  : > "$log_file"

  setsid -f bash -lc "
    cd '$workdir'
    echo \$$ > '$pid_file'
    exec $cmd
  " </dev/null >>"$log_file" 2>&1

  for _ in {1..40}; do
    if refresh_pid_file "$pid_file" "$pattern"; then
      echo "$name started: pid $(cat "$pid_file")"
      return 0
    fi
    sleep 0.25
  done

  echo "$name failed to start. See $log_file" >&2
  return 1
}

stop_service() {
  local name="$1"
  local pid_file="$2"
  local pattern="$3"

  refresh_pid_file "$pid_file" "$pattern" || true

  if ! is_running "$pid_file"; then
    echo "$name not running"
    return 0
  fi

  local pid
  pid="$(cat "$pid_file")"
  kill "$pid" 2>/dev/null || true

  for _ in {1..20}; do
    if ! refresh_pid_file "$pid_file" "$pattern"; then
      rm -f "$pid_file"
      echo "$name stopped"
      return 0
    fi
    sleep 0.25
  done

  while true; do
    pid="$(find_pid_by_pattern "$pattern")"
    if [[ -z "$pid" ]]; then
      break
    fi
    kill -9 "$pid" 2>/dev/null || true
    sleep 0.25
  done
  rm -f "$pid_file"
  echo "$name stopped with SIGKILL"
}

print_http_status() {
  local name="$1"
  local url="$2"
  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)"
  if [[ -z "$code" || "$code" == "000" ]]; then
    echo "$name http: down"
  else
    echo "$name http: $code"
  fi
}

status_service() {
  local name="$1"
  local pid_file="$2"
  local pattern="$3"

  refresh_pid_file "$pid_file" "$pattern" || true

  if is_running "$pid_file"; then
    echo "$name process: running (pid $(cat "$pid_file"))"
  else
    echo "$name process: stopped"
  fi
}

logs() {
  tail -n 80 -f "$BACKEND_LOG_FILE" "$FRONTEND_LOG_FILE"
}

start_all() {
  start_service "backend" "$BACKEND_DIR" "$BACKEND_PID_FILE" "$BACKEND_LOG_FILE" "$BACKEND_CMD" "$BACKEND_PATTERN"
  start_service "frontend" "$FRONTEND_DIR" "$FRONTEND_PID_FILE" "$FRONTEND_LOG_FILE" "$FRONTEND_CMD" "$FRONTEND_PATTERN"
}

stop_all() {
  stop_service "frontend" "$FRONTEND_PID_FILE" "$FRONTEND_PATTERN"
  stop_service "backend" "$BACKEND_PID_FILE" "$BACKEND_PATTERN"
}

status_all() {
  status_service "backend" "$BACKEND_PID_FILE" "$BACKEND_PATTERN"
  print_http_status "backend" "http://127.0.0.1:8000/health"
  status_service "frontend" "$FRONTEND_PID_FILE" "$FRONTEND_PATTERN"
  print_http_status "frontend" "http://127.0.0.1:5173/"
}

command="${1:-}"

case "$command" in
  start)
    start_all
    status_all
    ;;
  stop)
    stop_all
    ;;
  restart)
    stop_all
    start_all
    status_all
    ;;
  status)
    status_all
    ;;
  logs)
    logs
    ;;
  *)
    usage
    exit 1
    ;;
esac
