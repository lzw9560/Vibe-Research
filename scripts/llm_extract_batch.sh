#!/usr/bin/env bash
# 批量规则抽取：对前 50 只股票，每只拉 2 份研报，规则抽取实体到 inbox/
# 用法: bash scripts/llm_extract_batch.sh
set -uo pipefail

STOCKS_DIR="/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks"
SCRIPT="/Users/lizhiwei/project/code/stock/Vibe-Research/scripts/llm_extract.py"
LIMIT=2
MAX_CODES=50

# 取前 MAX_CODES 只股票代码（跳过 index.md），保证顺序稳定
mapfile -t CODES < <(for f in "$STOCKS_DIR"/*.md; do
    [ "$(basename "$f")" = "index.md" ] && continue
    basename "$f" .md
done | sort | head -n "$MAX_CODES")

echo "[BATCH] 共 ${#CODES[@]} 只股票，每只 limit=$LIMIT" >&2
ok=0; fail=0
for code in "${CODES[@]}"; do
    if out=$(python3 "$SCRIPT" --code "$code" --limit "$LIMIT" --quiet 2>/dev/null); then
        n=$(printf '%s\n' "$out" | grep -c .)
        echo "[OK] $code -> $n 文件"
        ok=$((ok+1))
    else
        echo "[SKIP] $code (无研报或失败)"
        fail=$((fail+1))
    fi
    sleep 2  # 防限流
done
echo "[DONE] 成功 $ok，跳过 $fail" >&2
