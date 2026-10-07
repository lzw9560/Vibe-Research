"""
长假节前效应 — ETF流与结构领域深挖
1. 信号复现 (指数 ETF)
2. ETF 折溢价节前变化 (premium = close/nav - 1)
3. 宽基 vs 行业 ETF 节前差异
4. 动量参考 (节前信号是否=前期涨幅的延续)
"""
import json, sys
from datetime import datetime, timedelta
from statistics import mean, median, stdev

CACHE = "/Users/lizhiwei/project/code/stock/Vibe-Research/.vibe-research"

with open(f"{CACHE}/index_ohlc_cache.json") as f:
    idx = json.load(f)
with open(f"{CACHE}/etf_premium_cache.json") as f:
    etf = json.load(f)

sh = idx["sh.000001"]
dates = [r["date"] for r in sh]
by_date = {r["date"]: r for r in sh}
date_set = set(dates)
date_idx = {d: i for i, d in enumerate(dates)}

# ---------- 1. build long-holiday list from trading calendar gaps ----------
holiday_gaps = []
for i in range(1, len(dates)):
    d0 = datetime.strptime(dates[i-1], "%Y-%m-%d")
    d1 = datetime.strptime(dates[i], "%Y-%m-%d")
    gap_days = (d1 - d0).days  # calendar days between consecutive trading days
    if gap_days >= 5:  # >=5 cal days => at least 3 non-weekend days off (Fri->Wed+)
        holiday_gaps.append({
            "last_pre": dates[i-1],
            "first_post": dates[i],
            "gap_days": gap_days,
            # weekday of last_pre
            "weekday": d0.weekday(),  # 0=Mon
            "month": d0.month,
        })

# classify long holidays: 春节(1-2月), 国庆(9-10月, combined中秋), 劳动节(5月), 其他(清明4月/端午6月/中秋9-10月)
def classify(g):
    m = datetime.strptime(g["last_pre"], "%Y-%m-%d").month
    if m in (1,2): return "春节"
    if m == 5: return "劳动节"
    if m in (9,10): return "国庆中秋"
    if m == 4: return "清明"
    if m == 6: return "端午"
    if m in (7,8): return "其他夏"
    if m in (11,12): return "其他冬"
    return "其他"

for g in holiday_gaps:
    g["type"] = classify(g)

# group by gap size
print("=== Trading-calendar long gaps (>=5 cal days) ===")
print(f"total gaps: {len(holiday_gaps)}")
from collections import Counter
print("by type:", Counter(g["type"] for g in holiday_gaps))
print("by gap_days:", Counter(g["gap_days"] for g in holiday_gaps))

# restrict to TRUE long holidays: gap >=7 cal days (Spring Fest ~9-11, National ~7-9, Labor Day golden week historically 7)
long_only = [g for g in holiday_gaps if g["gap_days"] >= 7]
print(f"\n=== Long holidays only (gap>=7 cal days): {len(long_only)} ===")
print("by type:", Counter(g["type"] for g in long_only))
for g in long_only:
    print(f"  {g['last_pre']} -> {g['first_post']} gap={g['gap_days']}d type={g['type']}")
