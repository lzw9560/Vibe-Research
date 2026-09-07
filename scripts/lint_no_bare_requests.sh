#!/usr/bin/env bash
# S164 R3: 裸 requests lint gate — 禁止裸调 requests.get/post on eastmoney/tencent host
#
# 所有东财/腾讯端点调用必须走 em_get（限流 + 熔断 + 代理降级防封路径，
# backend/data/transport.py）。裸 requests.get/post 直接打 eastmoney/tencent host
# 绕过防封 backbone，有 IP 封禁风险（§1.2 工程底线）。
#
# 两道检查（都须过）：
#   1. grep pass — 同行 literal protected-host URL（抓最常见裸调形态，快）
#   2. AST pass — backend/tools/lint_no_bare_requests.py（解析变量赋值/f-string
#      URL，抓 grep 看不到的间接裸调；比 grep 更全面）
#
# 为什么不只靠 grep：grep 只能抓同行 literal URL（如 requests.get('https://
# push2.eastmoney.com')），看不到 url 变量在别处赋值的情况。AST lint 遍历语法树
# 解析 _REPORT_API = "..." 这类变量再判 host，覆盖更全。grep + AST 双保险。
#
# 为什么不直接 grep 'requests\.(get|post)' 全抓：backend/ 有 34 处合法裸调
# （feishu/telegram/slack 等 notification webhook senders，非东财 host），全抓
# 会误报。必须按 protected host 过滤。
#
# whitelist（允许裸 requests）：
#   - data/transport.py — em_get 实现（限流/熔断/代理路径本身）
#   - proxy_pool.py    — proxy 健康检查裸调 push2his（by design）
# 排除目录：tests/ tools/ .venv/ __pycache__/（非生产代码 / 依赖）

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND="$REPO_ROOT/backend"

# Protected hosts — 东财 + 腾讯（须走 em_get 防封路径）
PROTECTED_RE='eastmoney\.com|tencent\.com|qq\.com|push2|fflow'

# 排除路径（whitelist + 非生产目录）
EXCLUDE_RE='\.venv/|data/transport\.py|proxy_pool\.py|/tests/|/tools/|/__pycache__/'

echo "=== S164 R3: 裸 requests lint gate ==="

# ---------------------------------------------------------------------------
# Pass 1: grep 同行 literal protected-host URL
# ---------------------------------------------------------------------------
# 不用 pipefail：grep 无匹配 exit 1 是正常的（=pass），|| true 兜底。
GREP_HITS=$(grep -rnE 'requests\.(get|post)' "$BACKEND" --include='*.py' \
  | grep -vE "$EXCLUDE_RE" \
  | grep -vE ':[0-9]+:\s*#' \
  | grep -E "$PROTECTED_RE" \
  || true)

if [ -n "$GREP_HITS" ]; then
  echo "[FAIL grep pass] 发现裸调 requests.get/post 打 protected host："
  echo "$GREP_HITS"
  echo ""
  echo "修复：改为 em_get（限流+熔断+代理降级防封路径）"
  echo "  from data.transport import eastmoney_get as em_get"
  echo "  r = em_get(url, params=...)"
  exit 1
fi
echo "[PASS grep pass] 无同行 literal protected-host 裸调"

# ---------------------------------------------------------------------------
# Pass 2: AST（解析变量/f-string URL，比 grep 更全面）
# ---------------------------------------------------------------------------
python3 "$BACKEND/tools/lint_no_bare_requests.py"
