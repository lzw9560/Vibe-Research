# -*- coding: utf-8 -*-
"""Fetch sh.000001 (上证指数) full-history daily K-line from baostock,
compute MA20, and label each trading day's regime (strong=close>MA20 / weak=close<MA20).
Caches result to .vibe-research/index_ma20_regime.json for downstream §44 lift scripts.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # S163 R3: repo root，不硬编码绝对路径
OUT = ROOT / ".vibe-research" / "index_ma20_regime.json"

import baostock as bs

lg = bs.login()
if lg.error_code != "0":
    print(f"baostock login failed: {lg.error_msg}", file=sys.stderr)
    sys.exit(1)

# query full history daily K for sh.000001
rs = bs.query_history_k_data_plus(
    "sh.000001",
    "date,close",
    start_date="2004-01-04",
    end_date="2026-09-06",
    frequency="d",
    adjustflag="3",  # no adjust for index
)
if rs.error_code != "0":
    print(f"query failed: {rs.error_msg}", file=sys.stderr)
    bs.logout()
    sys.exit(1)

rows = []
while rs.error_code == "0" and rs.next():
    rows.append(rs.get_row_data())

bs.logout()

# S163 R1 NOTE: baostock index kline（sh.000001，list_of_lists，仅 date+close）
# 不匹配 baostock_kline schema（需 OHLCV list_of_dicts）—— 待新建 'baostock_index_kline' schema
# （shape=list_of_lists，fields=date+close，用于指数 regime 派生，非个股 §44 verdict 输入）

print(f"fetched {len(rows)} index daily bars")
if not rows:
    print("no data", file=sys.stderr)
    sys.exit(1)

# build date -> close, compute MA20 regime
closes = []
regime = {}  # date -> {"close":..., "ma20":..., "regime":"strong"|"weak"}
for r in rows:
    d = str(r[0])[:10]
    try:
        c = float(r[1])
    except (ValueError, TypeError):
        continue
    closes.append((d, c))

# compute MA20 rolling
WINDOW = 20
for i, (d, c) in enumerate(closes):
    if i < WINDOW - 1:
        continue  # not enough history
    ma20 = sum(closes[j][1] for j in range(i - WINDOW + 1, i + 1)) / WINDOW
    regime[d] = {
        "close": c,
        "ma20": round(ma20, 4),
        "regime": "strong" if c > ma20 else "weak",
    }

OUT.write_text(json.dumps(regime, ensure_ascii=False))
print(f"wrote {len(regime)} regime labels to {OUT}")
print(f"date range: {closes[0][0]} -> {closes[-1][0]}")

# quick distribution
strong = sum(1 for v in regime.values() if v["regime"] == "strong")
weak = sum(1 for v in regime.values() if v["regime"] == "weak")
print(f"strong(bull): {strong} ({strong*100/len(regime):.1f}%)  weak(bear): {weak} ({weak*100/len(regime):.1f}%)")
