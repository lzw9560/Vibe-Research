# -*- coding: utf-8 -*-
"""Fetch sh.000001 (上证指数) full-history daily K-line from baostock,
compute MA20, and label each trading day's regime (strong=close>MA20 / weak=close<MA20).
Caches result to .vibe-research/index_ma20_regime.json for downstream §44 lift scripts.
"""
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # S163 R3: repo root，不硬编码绝对路径
OUT = ROOT / ".vibe-research" / "index_ma20_regime.json"
sys.path.insert(0, str(ROOT / "backend"))
from data_quality.schema_validator import validate_or_reject  # S163 R1: bad-data gate
from data.sources.baostock_src import fetch_bars

# query full history daily K for sh.000001（P2 DRY: 迁到 baostock_src）
bars = fetch_bars(
    "sh.000001", "2004-01-04", "2026-09-06",
    fields="date,close", adjustflag="3",  # no adjust for index
)
if not bars:
    print("baostock fetch failed (login? query?)", file=sys.stderr)
    sys.exit(1)

# validate_or_reject expects list_of_lists [date_str, close_str/float]
rows = [[b["date"], b["close"]] for b in bars]

# S163 R1: bad data gate — baostock index kline（list_of_lists，date+close）
rows = validate_or_reject("baostock_index_kline", rows, as_of=datetime.date.today().isoformat())

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
