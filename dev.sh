#!/bin/bash
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
LOG_DIR="$PROJECT_ROOT/.logs"

BACKEND_PORT=8900
FRONTEND_PORT=5899

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err() { echo -e "${RED}[ERROR]${NC} $1"; }

# 检查命令是否存在
check_cmd() {
  if ! command -v "$1" &> /dev/null; then
    err "缺少命令: $1，请先安装"
    exit 1
  fi
}

# 加载 nvm（如果存在）
load_nvm() {
  if [ -s "$HOME/.nvm/nvm.sh" ]; then
    # shellcheck disable=SC1090
    . "$HOME/.nvm/nvm.sh"
  fi
}

# 停止旧进程
stop_old() {
  info "检查并停止旧进程..."
  if lsof -Pi :$BACKEND_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    warn "端口 $BACKEND_PORT 被占用，尝试停止旧后端..."
    kill $(lsof -Pi :$BACKEND_PORT -sTCP:LISTEN -t) 2>/dev/null || true
    sleep 1
  fi
  if lsof -Pi :$FRONTEND_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    warn "端口 $FRONTEND_PORT 被占用，尝试停止旧前端..."
    kill $(lsof -Pi :$FRONTEND_PORT -sTCP:LISTEN -t) 2>/dev/null || true
    sleep 1
  fi
}

# 启动后端
start_backend() {
  info "启动后端 (端口 $BACKEND_PORT)..."
  mkdir -p "$LOG_DIR"

  # 检查 Python 虚拟环境
  if [ -d "$BACKEND_DIR/.venv" ]; then
    source "$BACKEND_DIR/.venv/bin/activate"
    info "使用虚拟环境: $BACKEND_DIR/.venv"
  else
    warn "未找到虚拟环境，使用系统 Python"
  fi

  cd "$BACKEND_DIR"
  uvicorn app:app --host 127.0.0.1 --port $BACKEND_PORT --reload > "$LOG_DIR/backend.log" 2>&1 &
  BACKEND_PID=$!
  info "后端已启动 (PID: $BACKEND_PID)"
}

# 启动前端
start_frontend() {
  info "启动前端 (端口 $FRONTEND_PORT)..."
  mkdir -p "$LOG_DIR"

  cd "$FRONTEND_DIR"

  # 检查 node_modules 是否健康
  if [ ! -d "node_modules" ] || [ ! -f "node_modules/.package-lock.json" ]; then
    warn "node_modules 缺失或不完整，执行 npm install..."
    rm -rf node_modules package-lock.json
    npm install
  else
    info "node_modules 已存在，跳过安装"
  fi

  # 检查 Node.js 版本
  NODE_VERSION=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
  if [ "$NODE_VERSION" -lt 18 ]; then
    err "Node.js 版本过低 (当前: $(node -v))，需要 >= 18"
    exit 1
  fi

  npm run dev > "$LOG_DIR/frontend.log" 2>&1 &
  FRONTEND_PID=$!
  info "前端已启动 (PID: $FRONTEND_PID)"
}

# 等待服务就绪
wait_for_service() {
  local port=$1
  local name=$2
  local max_attempts=30
  local attempt=1

  info "等待 $name 就绪 (端口 $port)..."
  while [ $attempt -le $max_attempts ]; do
    if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$port" 2>/dev/null | grep -q "200\|404"; then
      info "$name 已就绪 ✓"
      return 0
    fi
    sleep 1
    attempt=$((attempt + 1))
  done

  warn "$name 启动超时，但进程可能仍在启动中..."
  return 1
}

# 显示状态
show_status() {
  echo ""
  info "=========================================="
  info "Vibe-Research 开发环境已启动"
  info "=========================================="
  echo -e "  前端: ${GREEN}http://localhost:$FRONTEND_PORT${NC}"
  echo -e "  后端: ${GREEN}http://127.0.0.1:$BACKEND_PORT${NC}"
  echo -e "  API 文档: ${GREEN}http://127.0.0.1:$BACKEND_PORT/docs${NC}"
  echo ""
  info "日志文件:"
  echo "  后端: $LOG_DIR/backend.log"
  echo "  前端: $LOG_DIR/frontend.log"
  echo ""
  info "停止服务: 按 Ctrl+C 或运行 ./stop-dev.sh"
  echo ""
}

# 主流程
main() {
  info "启动 Vibe-Research 开发环境..."

  # 加载 nvm（让 node/npm 指向 nvm 管理的版本）
  load_nvm

  check_cmd "uvicorn"
  check_cmd "npm"
  check_cmd "curl"

  stop_old
  start_backend
  start_frontend

  # 等待后端就绪（前端 vite 启动较快，主要等后端）
  wait_for_service $BACKEND_PORT "后端 API"

  show_status

  # 保持脚本运行，等待用户 Ctrl+C
  info "按 Ctrl+C 停止所有服务..."
  trap 'echo ""; info "正在停止服务..."; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true; exit 0' INT TERM

  # 等待后台进程
  wait
}

main
