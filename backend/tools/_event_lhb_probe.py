# -*- coding: utf-8 -*-
"""事件 deep dive v3：zt_buy（涨停榜+机构净买）按净买额分大/小 + 持有2日。
看大额机构净买是否 lift 更高、持有2日是否更稳。临时探针。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.first_board_layer_lift import _to_float, _winrate, day_paired_lift, four_state
import statistics
import akshare as ak

print("拉龙虎榜 2026-01-01~2026-08-18 ...", flush=True)
df = ak.stock_lhb_detail_em(start_date="20260101", end_date="20260818")
print(f"rows: {len(df)}", flush=True)
if df is None or len(df) == 0:
    sys.exit(1)

# zt_buy 子集：涨停榜 + 机构净买
zt_buy = []  # [{date, net_buy, r1, r2}]
for _, row in df.iterrows():
    d = str(row.get("上榜日", "")).strip()
    r1 = _to_float(row.get("上榜后1日"))
    r2 = _to_float(row.get("上榜后2日"))
    nb = _to_float(row.get("龙虎榜净买额"))
    reason = str(row.get("上榜原因", ""))
    if r1 is None or r1 != r1 or not d or nb is None:
        continue
    is_zt = ("涨幅" in reason) or ("涨停" in reason) or ("连涨" in reason)
    if not is_zt or nb <= 0:
        continue
    zt_buy.append({"date": d, "net_buy": nb, "r1": r1, "r2": r2})

print(f"zt_buy: {len(zt_buy)} 行")

# 净买额中位数分大/小
nbs = [x["net_buy"] for x in zt_buy]
med = statistics.median(nbs)
big = [x for x in zt_buy if x["net_buy"] >= med]
small = [x for x in zt_buy if x["net_buy"] < med]

def by_day(items, key="r1"):
    out = {}
    for x in items:
        v = x[key]
        if v is None or v != v:
            continue
        out.setdefault(x["date"], []).append(v)
    return out

def wms(items, key, label):
    rs = [x[key] for x in items if x[key] is not None and x[key] == x[key]]
    if not rs:
        print(f"  {label}: 空"); return
    print(f"  {label}: n={len(rs)} winrate={_winrate(rs):.4f} mean={statistics.mean(rs):.4f}%")

print("\n=== zt_buy 持有1日 vs 2日 ===")
wms(zt_buy, "r1", "zt_buy 持1日")
wms(zt_buy, "r2", "zt_buy 持2日")

print("\n=== zt_buy 大额 vs 小额（净买额中位数分）===")
print(f"  净买额中位数: {med:.0f}")
wms(big, "r1", "大额 持1日")
wms(small, "r1", "小额 持1日")

print("\n=== day-paired lift（大额 vs 小额，持1日）===")
lb = by_day(big, "r1")
ls = by_day(small, "r1")
if lb and ls:
    res = day_paired_lift(lb, ls)
    lift = res["winrate_lift_avg"]
    print(f"  lift={lift} n={res['surv_n_pooled']} status={four_state(lift, res['surv_n_pooled'])}")
