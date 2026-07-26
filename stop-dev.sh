#!/bin/bash
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT=8900
FRONTEND_PORT=5899

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

stop_port() {
  local port=$1
  local name=$2
  if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
    warn "停止 $name (端口 $port)..."
    kill $(lsof -Pi :$port -sTCP:LISTEN -t) 2>/dev/null || true
    sleep 1
    info "$name 已停止"
  else
    info "$name 未运行"
  fi
}

info "停止 Vibe-Research 开发环境..."
stop_port $BACKEND_PORT "后端"
stop_port $FRONTEND_PORT "前端"
info "所有服务已停止"
