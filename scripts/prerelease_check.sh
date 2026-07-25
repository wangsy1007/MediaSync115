#!/usr/bin/env bash
# MediaSync115 上线前一键回归：容器就绪 → pytest → API 冒烟 → Playwright UI（可选 --live）
set -euo pipefail

BASE_URL="${MEDIASYNC_BASE_URL:-http://127.0.0.1:5173}"
USERNAME="${MEDIASYNC_USER:-admin}"
PASSWORD="${MEDIASYNC_PASSWORD:-password}"
CONTAINER_NAME="${MEDIASYNC_CONTAINER:-mediasync115}"
READY_TIMEOUT_SEC="${READY_TIMEOUT_SEC:-180}"
LIVE=0
SKIP_UNIT=0
SKIP_API=0
SKIP_UI=0
STRICT=0

usage() {
  cat <<'EOF'
Usage: ./scripts/prerelease_check.sh [options]

Options:
  --base-url URL       服务地址 (default: http://127.0.0.1:5173)
  --username USER      登录用户 (default: admin / MEDIASYNC_USER)
  --password PASS      登录密码 (default: password / MEDIASYNC_PASSWORD)
  --live               额外跑实网转存/订阅队列冒烟
  --skip-unit          跳过 pytest
  --skip-api           跳过 API 冒烟
  --skip-ui            跳过 Playwright
  --strict             API 冒烟 WARN 也失败
  --container NAME     Docker 容器名 (default: mediasync115)
  -h, --help           显示帮助
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url) BASE_URL="$2"; shift 2 ;;
    --username) USERNAME="$2"; shift 2 ;;
    --password) PASSWORD="$2"; shift 2 ;;
    --live) LIVE=1; shift ;;
    --skip-unit) SKIP_UNIT=1; shift ;;
    --skip-api) SKIP_API=1; shift ;;
    --skip-ui) SKIP_UI=1; shift ;;
    --strict) STRICT=1; shift ;;
    --container) CONTAINER_NAME="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PASSED=()
FAILED=()

step() { printf '\n==> %s\n' "$1"; }

wait_http_ok() {
  local url="$1"
  local timeout_sec="$2"
  local last=""
  local started
  started="$(date +%s)"
  while true; do
    if curl -fsS --max-time 10 "$url" >/dev/null 2>&1; then
      return 0
    fi
    last="curl failed"
    if (( "$(date +%s)" - started >= timeout_sec )); then
      echo "等待服务就绪超时: $url ($last)" >&2
      return 1
    fi
    sleep 2
  done
}

resolve_python() {
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
  elif command -v python >/dev/null 2>&1; then
    echo "python"
  else
    echo ""
  fi
}

run_python_script() {
  local script_path="$1"
  shift
  local py
  py="$(resolve_python)"
  if [[ -n "$py" ]]; then
    echo "使用本机 Python: $py"
    "$py" "$script_path" "$@"
    return $?
  fi
  if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
    echo "本机无可用 Python，且容器 $CONTAINER_NAME 未运行" >&2
    return 1
  fi
  local remote="/tmp/$(basename "$script_path")"
  echo "本机无 Python，改用 docker exec $CONTAINER_NAME"
  docker cp "$script_path" "${CONTAINER_NAME}:${remote}"
  docker exec \
    -e "MEDIASYNC_BASE_URL=$BASE_URL" \
    -e "MEDIASYNC_USER=$USERNAME" \
    -e "MEDIASYNC_PASSWORD=$PASSWORD" \
    "$CONTAINER_NAME" python "$remote" "$@"
}

run_pytest() {
  local image
  image="$(docker inspect -f '{{.Config.Image}}' "$CONTAINER_NAME" 2>/dev/null || true)"
  if [[ -z "$image" ]]; then
    image="mediasync115:latest"
  fi
  echo "在临时容器中运行 pytest（镜像: $image）"
  docker run --rm \
    -v "$REPO_ROOT/backend:/work" \
    -w /work \
    -e "DATABASE_URL=sqlite+aiosqlite:///./data/prerelease_unit.db" \
    -e "TMDB_API_KEY=test-api-key" \
    -e "APP_NAME=MediaSync115-Prerelease" \
    --entrypoint "" \
    "$image" \
    sh -c "pip install -q pytest pytest-asyncio pytest-cov && mkdir -p data && pytest -q --tb=line"
}

echo "MediaSync115 上线前回归"
echo "仓库: $REPO_ROOT"
echo "BaseUrl: $BASE_URL"

step "L0 等待服务就绪"
if wait_http_ok "$BASE_URL/healthz" "$READY_TIMEOUT_SEC"; then
  PASSED+=("L0_ready")
else
  FAILED+=("L0_ready")
  echo "FAIL: 服务未就绪" >&2
  exit 1
fi
if ! wait_http_ok "http://127.0.0.1:9008/healthz" 30; then
  echo "WARN: 9008/healthz 不可达（可忽略若未映射该端口）"
fi

if [[ "$SKIP_UNIT" -eq 0 ]]; then
  step "L1 后端 pytest"
  if run_pytest; then
    PASSED+=("L1_pytest")
  else
    echo "FAIL: pytest" >&2
    FAILED+=("L1_pytest")
  fi
else
  echo "跳过 L1 pytest (--skip-unit)"
fi

if [[ "$SKIP_API" -eq 0 ]]; then
  step "L2 API 模块冒烟"
  api_args=(--base-url "$BASE_URL" --username "$USERNAME" --password "$PASSWORD")
  if [[ "$STRICT" -eq 1 ]]; then
    api_args+=(--strict)
  fi
  if run_python_script "$REPO_ROOT/scripts/prerelease_api_smoke.py" "${api_args[@]}"; then
    PASSED+=("L2_api_smoke")
  else
    echo "FAIL: API smoke" >&2
    FAILED+=("L2_api_smoke")
  fi
else
  echo "跳过 L2 API smoke (--skip-api)"
fi

if [[ "$LIVE" -eq 1 ]]; then
  step "L4 实网转存/订阅队列冒烟 (--live)"
  if run_python_script \
    "$REPO_ROOT/backend/tests/run_live_subscription_transfer_smoke.py" \
    --base-url "$BASE_URL" \
    --username "$USERNAME" \
    --password "$PASSWORD"; then
    PASSED+=("L4_live")
  else
    echo "FAIL: live smoke" >&2
    FAILED+=("L4_live")
  fi
fi

if [[ "$SKIP_UI" -eq 0 ]]; then
  step "L3 Playwright UI 冒烟"
  if [[ ! -d "$REPO_ROOT/frontend/node_modules" ]]; then
    echo "安装前端依赖..."
    (cd "$REPO_ROOT/frontend" && npm ci)
  fi
  export PLAYWRIGHT_FRONTEND_BASE_URL="$BASE_URL"
  export PLAYWRIGHT_BACKEND_HEALTH_URL="$BASE_URL/healthz"
  if (cd "$REPO_ROOT/frontend" && npm run test:smoke); then
    PASSED+=("L3_ui_smoke")
  else
    echo "FAIL: Playwright" >&2
    FAILED+=("L3_ui_smoke")
  fi
else
  echo "跳过 L3 UI smoke (--skip-ui)"
fi

echo ""
echo "======== 汇总 ========"
echo "通过: ${PASSED[*]:-}"
if [[ "${#FAILED[@]}" -gt 0 ]]; then
  echo "失败: ${FAILED[*]}" >&2
  exit 1
fi
echo "全部通过，可以上线验证这一轮基础功能。"
exit 0
