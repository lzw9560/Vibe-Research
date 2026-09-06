# -*- coding: utf-8 -*-
# 三窗口分解 verdict (2026-09-06, baostock kline_cache + gene_scores 3362 obs):
#   隔夜gap(D收→D+1开) mean+1.30% winrate54.3% | D+1日内(开→收) mean+0.03% winrate46.2%
#   path(D+1开→exit -3/+8/3) mean+0.67% median-3.00% winrate36.3%
# 证:edge在隔夜gap段(正),D+1日内~0,path=反转负段。§44v1 entry=D+1开盘miss gap。
# §44v2 reframe:对selection而言§44测对了(D+1开盘对continuation是正确口径),bug是外推成'无edge'。
"""验证窗口假设：涨停股隔夜 gap（D 收盘→D+1 开盘）vs D+1 intraday（开→收）vs path（D+1 开→D+4）。
若隔夜 gap 正 + path 负 = 我框架测错窗口（miss 隔夜正 edge，只测反转负段）。"""
import bisect
import datetime, json, sqlite3, sys, statistics
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]  # S163 R3: repo root，不硬编码绝对路径
sys.path.insert(0, str(ROOT / "backend"))
from strategies.kline_returns import simulate_holding
from data_quality.schema_validator import validate_or_reject  # S163 R1: bad-data gate
KLINE = ROOT / ".vibe-research" / "baostock_kline_cache.json"
DB = ROOT / ".vibe-research" / "gene_scores.db"
cache = json.loads(KLINE.read_bytes())
# S163 R1: 坏 bar（缺字段/负价/high<low/stale/空/错型）拒绝进 §44 verdict
validate_or_reject("baostock_kline",
                   [b for bars in cache.values() for b in bars],
                   as_of=datetime.date.today().isoformat())

# build trading calendar for date-adjacency check (MEDIUM #3)
_all_dates = sorted({b["date"] for bars in cache.values() for b in bars})

def _calendar_next(date_str):
    """Next trading day after date_str. None if date is last."""
    idx = bisect.bisect_left(_all_dates, date_str)
    if idx < len(_all_dates) and _all_dates[idx] == date_str:
        return _all_dates[idx + 1] if idx + 1 < len(_all_dates) else None
    if idx < len(_all_dates):
        return _all_dates[idx]
    return None

conn = sqlite3.connect(str(DB), timeout=10)
pairs = conn.execute("SELECT DISTINCT date, code FROM gene_scores WHERE data_source='eastmoney_live' ORDER BY date").fetchall()
conn.close()

overnight = []   # (D close → D+1 open) / D close  隔夜 gap
intraday = []    # (D+1 close - D+1 open) / D+1 open  D+1 日内（H2 o2c）
path_ret = []    # simulate_holding D+1 open → exit
n_suspended = 0  # MEDIUM #3: count non-adjacent (D+1 suspended) skips
for D, rawcode in pairs:
    code = str(rawcode).zfill(6)
    bars = cache.get(code)
    if not bars: continue
    d_idx = next((i for i,b in enumerate(bars) if str(b["date"])[:10] == D), None)
    if d_idx is None or d_idx+1 >= len(bars): continue
    # date adjacency (MEDIUM #3): bars[d_idx+1] must be calendar-next of D
    expected_next = _calendar_next(bars[d_idx]["date"])
    if expected_next is not None and bars[d_idx+1]["date"] != expected_next:
        n_suspended += 1
        continue
    d_close = bars[d_idx].get("close") or 0
    d1_open = bars[d_idx+1].get("open") or 0
    d1_close = bars[d_idx+1].get("close") or 0
    if not d_close or not d1_open: continue
    # volume guard (LOW #9): skip zero-volume suspended bars
    if bars[d_idx+1].get("volume", 0) <= 0: continue
    overnight.append((d1_open - d_close) / d_close * 100)
    if d1_open: intraday.append((d1_close - d1_open) / d1_open * 100)
    sim = simulate_holding(bars, D, -3.0, 8.0, 3)
    if sim: path_ret.append(sim["return_pct"])

print(f"date-adjacency: skipped {n_suspended} non-adjacent (D+1 suspended) picks")

def stats(name, vals):
    if not vals: print(f"  {name}: n=0"); return
    pos = sum(1 for v in vals if v > 0)
    print(f"  {name}: n={len(vals)} mean={statistics.mean(vals):.2f}% median={statistics.median(vals):.2f}% winrate={pos*100/len(vals):.1f}%")

print(f"涨停股 D+1 三窗口对比（%）：")
stats("隔夜 gap（D 收盘→D+1 开盘）", overnight)
stats("D+1 日内（开→收，H2 o2c）", intraday)
stats("path（D+1 开→exit，我框架 -3/+8/3）", path_ret)
print(f"\n若隔夜 gap 正 + path 负 → 窗口假设成立（我框架 miss 隔夜正 edge）")
print(f"注：隔夜 gap 不可交易捕获——涨停股 D 收盘 sealed 买不到，除非盘中打板（封板前买）")
