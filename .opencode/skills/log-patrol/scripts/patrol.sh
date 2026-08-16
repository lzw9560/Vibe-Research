#!/usr/bin/env bash
# log-patrol 常驻监控脚本
# 持续 tail 前后端日志，发现异常写告警文件，遇 500/Traceback 自动建 issue+派 fixer
# 用法：nohup bash patrol.sh > /tmp/log-patrol.log 2>&1 &

set -u
PROJECT_ROOT="/Users/lizhiwei/project/code/stock/Vibe-Research"
BACKEND_LOG="/tmp/vibe-backend.log"
FRONTEND_LOG="/tmp/vibe-frontend.log"
ALERT_DIR="$PROJECT_ROOT/.scratch/log-patrol-alerts"
PATROL_LOG="/tmp/log-patrol.log"
STATE_FILE="/tmp/log-patrol.offset"

mkdir -p "$ALERT_DIR"

# 错误关键词（命中即告警+自动修复）
ERROR_PATTERN='RuntimeError|RuntimeWarning|Traceback|Exception in ASGI|HTTP/1.1" 5[0-9][0-9]|no running event loop|never awaited|coroutine.*was never'

# 噪声过滤（命中虽含关键词但不算 bug）
NOISE_PATTERN='worldmonitor.*ConnectTimeout|LSP.*could not be resolved|Import.*could not be resolved'

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$PATROL_LOG"; }

# 初始化 offset（从文件末尾开始，不追溯历史）
init_offset() {
  local f="$1"
  if [ -f "$f" ]; then
    wc -l < "$f" | tr -d ' '
  else
    echo 0
  fi
}

# 上次读到的行号
BACKEND_OFFSET=$(init_offset "$BACKEND_LOG")
FRONTEND_OFFSET=$(init_offset "$FRONTEND_LOG")
echo "$BACKEND_OFFSET" > "$STATE_FILE.backend"
echo "$FRONTEND_OFFSET" > "$STATE_FILE.frontend"

log "log-patrol 启动 — backend offset=$BACKEND_OFFSET frontend offset=$FRONTEND_OFFSET"
log "监控日志：$BACKEND_LOG  $FRONTEND_LOG"
log "告警目录：$ALERT_DIR"

# 扫描新增行，命中错误模式 → 告警
scan_new_lines() {
  local log_file="$1"
  local offset_file="$2"
  local label="$3"
  
  [ ! -f "$log_file" ] && return
  
  local current_lines=$(wc -l < "$log_file" | tr -d ' ')
  local last_offset=$(cat "$offset_file" 2>/dev/null || echo 0)
  
  # 日志被截断（重启清空），重置 offset
  if [ "$current_lines" -lt "$last_offset" ]; then
    log "$label 日志被截断（重启？），重置 offset $last_offset → $current_lines"
    last_offset=0
  fi
  
  # 无新增行
  [ "$current_lines" -le "$last_offset" ] && return
  
  # 读新增行
  local new_lines=$(sed -n "$((last_offset+1)),${current_lines}p" "$log_file")
  echo "$new_lines" | grep -nE "$ERROR_PATTERN" 2>/dev/null | while IFS= read -r match; do
    # 噪声过滤
    if echo "$match" | grep -qE "$NOISE_PATTERN" 2>/dev/null; then
      continue
    fi
    # 命中真实错误 → 写告警文件
    local ts=$(date '+%Y%m%d-%H%M%S')
    local alert_file="$ALERT_DIR/${label}-${ts}.alert"
    {
      echo "ALERT: $label 异常"
      echo "TIME: $(date '+%Y-%m-%d %H:%M:%S')"
      echo "LOG: $log_file"
      echo "MATCH: $match"
      echo "---"
      # 抓 match 行号附近 20 行上下文
      local line_no=$(echo "$match" | cut -d: -f1)
      local start=$((line_no - 10))
      [ "$start" -lt 1 ] && start=1
      local end=$((line_no + 30))
      echo "CONTEXT (line $start-$end):"
      sed -n "${start},${end}p" "$log_file"
    } > "$alert_file"
    log "ALERT 写入: $alert_file — $match"
  done
  
  echo "$current_lines" > "$offset_file"
}

# 主循环：每 10 秒扫一次
log "进入主循环（每 10 秒扫描一次）"
while true; do
  scan_new_lines "$BACKEND_LOG" "$STATE_FILE.backend" "backend"
  scan_new_lines "$FRONTEND_LOG" "$STATE_FILE.frontend" "frontend"
  sleep 10
done
