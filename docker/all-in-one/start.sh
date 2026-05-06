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

# ===== 第一阶段：启动后端 =====
echo "========================================="
echo "  MediaSync115 容器启动"
echo "========================================="
echo "[$(date '+%H:%M:%S')] 后端启动中..."
uvicorn main:app --host 127.0.0.1 --port 8000 &
uvicorn_pid=$!

wait_for_backend() {
  local max_wait=300
  local elapsed=0
  local last_progress=0

  while [ "${elapsed}" -lt "${max_wait}" ]; do
    if curl -sf --max-time 2 http://127.0.0.1:8000/health >/dev/null 2>&1; then
      echo "[$(date '+%H:%M:%S')] ✓ 后端启动成功（耗时 ${elapsed}s）"
      return 0
    fi

    if ! kill -0 "${uvicorn_pid}" 2>/dev/null; then
      echo "[$(date '+%H:%M:%S')] ✗ 后端进程意外退出，请检查上方日志"
      return 1
    fi

    # 每 5 秒输出一次等待进度
    if [ $((elapsed - last_progress)) -ge 5 ]; then
      echo "[$(date '+%H:%M:%S')]   等待后端就绪...（已等待 ${elapsed}s）"
      last_progress=${elapsed}
    fi

    sleep 1
    elapsed=$((elapsed + 1))
  done

  echo "[$(date '+%H:%M:%S')] ✗ 后端在 ${max_wait}s 内未能就绪"
  return 1
}

if ! wait_for_backend; then
  shutdown
  wait "${uvicorn_pid}" 2>/dev/null || true
  exit 1
fi

# ===== 第二阶段：启动前端(nginx) =====
echo "[$(date '+%H:%M:%S')] 前端启动中..."

# 注入 Emby 代理地址到 nginx 配置
EMBY_PROXY_HOST="${EMBY_PROXY_HOST:-host.docker.internal}"
EMBY_PROXY_PORT="${EMBY_PROXY_PORT:-8096}"
sed -i "s/__EMBY_HOST__/${EMBY_PROXY_HOST}/g" /etc/nginx/nginx.conf
sed -i "s/__EMBY_PORT__/${EMBY_PROXY_PORT}/g" /etc/nginx/nginx.conf
echo "[$(date '+%H:%M:%S')] Emby 代理目标: ${EMBY_PROXY_HOST}:${EMBY_PROXY_PORT}"

# 配置检查
if ! nginx -t 2>&1; then
  echo "[$(date '+%H:%M:%S')] ✗ nginx 配置检查失败"
  shutdown
  wait "${uvicorn_pid}" 2>/dev/null || true
  exit 1
fi

nginx -g 'daemon off;' &
nginx_pid=$!

# 等待 nginx 进程启动并验证
sleep 1
if kill -0 "${nginx_pid}" 2>/dev/null; then
  echo "[$(date '+%H:%M:%S')] ✓ 前端(nginx)启动成功（端口 5173/9008/8099）"
  echo "========================================="
  echo "  MediaSync115 已就绪"
  echo "========================================="
else
  echo "[$(date '+%H:%M:%S')] ✗ nginx 启动失败"
  shutdown
  wait "${uvicorn_pid}" 2>/dev/null || true
  exit 1
fi

# ===== 运行中：监控进程 =====
wait -n "${uvicorn_pid}" "${nginx_pid}"
exit_code=$?

echo "[$(date '+%H:%M:%S')] 进程退出（exit_code=${exit_code}），正在关闭..."
shutdown

wait "${uvicorn_pid}" 2>/dev/null || true
wait "${nginx_pid}" 2>/dev/null || true

exit "${exit_code}"
