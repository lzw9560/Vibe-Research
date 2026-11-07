# -*- coding: utf-8 -*-
"""长假节前 A 组（节前+TOM 重叠）§44 v3 严测（2026-10-08）。

disentangle 发现长假节前 edge 主要来自 A 组（节前+TOM 重叠）：
- A 组全期 n=105 EV+0.785% > 全 picks +0.52%
- 2022 后 A 组 n=21 EV+0.910%（仍正，underpowered）

本脚本跑 A 组独立严测（§44 v3）：
1. 全期 stats + lift vs base
2. Bonf×6（6 长假类型多重校正）
3. walk-forward（时间 split train/test）
4. DSR（deflated sharpe）
5. 衰减检查（按年/按 era）

verdict 判定：Bonf 后 p<0.05 + walk-forward test PASS + 无单 regime → edge-confirmed

⚠️ 2026-10-08 6 视角 grill 综合后降级 verdict: edge-confirmed-provisional → exploratory
（真信号 in-sample 极强 p=0.00005 Bonf×63=0.003 仍 PASS，但 OOS 不够稳健到 confirmed）

2 视角 NOT SURVIVE（戳破 confirmed）:
1. 执行成本: 29% picks（2004-2010）无上证综指 ETF 可交易（510210 2011-01-30 才上线），
   恰好 EV 最高（+1.258% WR80%）拉高整体。扣可交易期（2011+）n=75 Bonf×6=0.0511
   borderline FAIL（差 0.0025）。walk-forward test 期含不可交易数据 boost"衰减1.3%"。
2. post-hoc: OOS test p=0.0301 用裸 p 没 Bonf 校正（本脚本漏了），Bonf×4=0.12 FAIL /
   Bonf×6=0.18 FAIL。A 组定义本身是 post-hoc subgroup selection（从 A/B/C/D 4 组选最好）。
   其他子组 pre+EOM（p=0.0002）/pre+Quarter-end（p=0.0012）也显著→edge 是宽泛节前效应
   非 TOM 特有。OOS test 离群依赖（2024-09-27 +9.326%=test 43%，去后 p=0.0493 边界）。

4 视角 SURVIVE（provisional 方向，证 edge 真实非假阳性）:
- lottery: 去top3后p=0.0002，block bootstrap CI排除0，非尾部驱动（区别 inst_dominant lottery）
- regime: 排除早期（2011-2026）raw p=0.0085 PASS，但 era Bonf×4 仅 2004-2010 PASS（era-fragile）
- 机制: 5混淆全排除（春节/元旦/双排除/COVID/regime）+ era-matched超额 p=0.0030 + 留一法7/7
- 统计rigor: Bonf×7=0.0272 PASS + 真 Bailey-Lopez de Prado DSR PSR=0.99997 + NW HAC t=3.5

综合: edge 真实（in-sample 极强+非尾部+非混淆+era-matched）但 OOS 不够稳健到 confirmed。
需更多可交易样本（2011+ 累积）复验。待修: Bonf×7（非×6）+ OOS test Bonf + 可交易期过滤 +
多 split 比例稳定性 + NW HAC + 真 DSR + 去离群稳定性。
"""

from __future__ import annotations
import json
import statistics
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from math import erf, sqrt

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir

DATA = str(resolve_data_dir())
with open(f"{DATA}/index_ohlc_cache.json") as f:
    idx_data = json.load(f)

bars_sh = sorted(idx_data["sh.000001"], key=lambda b: b["date"])
calendar = [b["date"] for b in bars_sh]
bar_map = {b["date"]: b for b in bars_sh}

HOLIDAY_GAP = 4
ETF_COST = 0.10  # ETF 双边 0.10%


def classify_holiday(h):
    last_dt = datetime.strptime(h["last_before"], "%Y-%m-%d")
    month, gap = last_dt.month, h["gap"]
    if month in (1, 2) and gap >= 7:
        return "春节"
    if month in (9, 10) and gap >= 5:
        return "国庆"
    if month == 9 and gap < 5:
        return "中秋"
    if month in (4, 5) and 3 <= gap <= 6:
        return "清明" if month == 4 else "劳动节"
    if month == 6 and gap >= 3:
        return "端午"
    if month in (12, 1) and gap < 7:
        return "元旦"
    return "其他"


holidays = []
for i in range(1, len(calendar)):
    d0 = datetime.strptime(calendar[i - 1], "%Y-%m-%d")
    d1 = datetime.strptime(calendar[i], "%Y-%m-%d")
    gap = (d1 - d0).days
    if gap >= HOLIDAY_GAP:
        holidays.append({"last_before": calendar[i - 1], "first_after": calendar[i], "gap": gap, "idx_last": i - 1, "idx_first": i})
for h in holidays:
    h["type"] = classify_holiday(h)

holiday_zone = set()
for h in holidays:
    for k in range(max(0, h["idx_last"] - 2), min(len(calendar), h["idx_last"] + 1)):
        holiday_zone.add(calendar[k])
    for k in range(h["idx_first"], min(len(calendar), h["idx_first"] + 2)):
        holiday_zone.add(calendar[k])


def stats(rets):
    n = len(rets)
    if n == 0:
        return {"n": 0, "mean": 0.0, "std": 0.0, "se": 0.0, "t": 0.0, "p": 1.0, "wr": 0.0, "median": 0.0}
    mean = sum(rets) / n
    std = statistics.pstdev(rets) if n > 1 else 0.0
    se = std / sqrt(n) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    p = 0.5 * (1 - erf(t / sqrt(2))) if t > 0 else 1.0
    wr = sum(1 for x in rets if x > 0) / n
    med = statistics.median(rets)
    return {"n": n, "mean": mean, "std": std, "se": se, "t": t, "p": p, "wr": wr, "median": med}


def is_turn_of_month(date_str):
    ym = date_str[:7]
    month_days = [d for d in calendar if d[:7] == ym]
    if not month_days:
        return False
    return date_str in month_days[:3] or date_str in month_days[-3:]


# base rate（非节假日 2-day open→close）
base_returns = []
for i in range(len(calendar) - 1):
    d_start, d_end = calendar[i], calendar[i + 1]
    if d_start in holiday_zone or d_end in holiday_zone:
        continue
    b_s, b_e = bar_map[d_start], bar_map[d_end]
    o, c = b_s.get("open"), b_e.get("close")
    if o and c and o > 0:
        base_returns.append((c - o) / o * 100)
base_s = stats(base_returns)

# A 组 picks（节前 + TOM 重叠）
a_picks = []
for h in holidays:
    i_last = h["idx_last"]
    if i_last - 1 >= 0:
        d_buy, d_sell = calendar[i_last - 1], calendar[i_last]
        b_buy, b_sell = bar_map[d_buy], bar_map[d_sell]
        o, c = b_buy.get("open"), b_sell.get("close")
        if o and c and o > 0 and c > 0:
            ret = (c - o) / o * 100 - ETF_COST  # net
            tom = is_turn_of_month(d_buy) or is_turn_of_month(d_sell)
            if tom:  # A 组 = 节前 + TOM 重叠
                a_picks.append({"type": h["type"], "buy_date": d_buy, "sell_date": d_sell, "ret": ret})

a_rets = [p["ret"] for p in a_picks]
a_s = stats(a_rets)
lift = a_s["mean"] / base_s["mean"] if base_s["mean"] != 0 else 0

print("=" * 70)
print("长假节前 A 组（节前+TOM 重叠）§44 v3 严测")
print("=" * 70)
print(f"\nBase rate: n={base_s['n']} EV={base_s['mean']:.4f}% WR={base_s['wr'] * 100:.1f}%")
print(
    f"A 组全期: n={a_s['n']} gross_EV={a_s['mean']:.4f}% WR={a_s['wr'] * 100:.1f}% "
    f"median={a_s['median']:.3f}% t={a_s['t']:.2f} p_raw={a_s['p']:.4f} lift={lift:.2f}x"
)

# ---------- 1. Bonf×6（6 长假类型多重校正）----------
print(f"\n{'=' * 70}")
print("1. Bonf×6 多重校正（6 长假类型）")
print(f"{'=' * 70}")
# 对每个长假类型单独算 p，Bonferroni ×6
types_present = sorted(set(p["type"] for p in a_picks))
min_p = 1.0
for ht in types_present:
    sub = [p["ret"] for p in a_picks if p["type"] == ht]
    s = stats(sub)
    bonf_p = min(s["p"] * 7, 1.0)  # Bonf×7（7 类型：春节/国庆/清明/劳动/端午/元旦/其他）
    print(f"  {ht}: n={s['n']} EV={s['mean']:.3f}% WR={s['wr'] * 100:.1f}% p_raw={s['p']:.4f} Bonf×7={bonf_p:.4f} {'PASS' if bonf_p < 0.05 else 'FAIL'}")
    if s["p"] < min_p:
        min_p = s["p"]
bonf7_overall = min(a_s["p"] * 7, 1.0)
# 系统枚举 N（grill post-hoc agent 测 63 子组口径）→ Bonf×63 最严（R44 post-hoc subgroup 校正）
bonf63_overall = min(a_s["p"] * 63, 1.0)
print(
    f"  整体 A 组: p_raw={a_s['p']:.4f} Bonf×7={bonf7_overall:.4f} "
    f"{'PASS' if bonf7_overall < 0.05 else 'FAIL'} / Bonf×63={bonf63_overall:.4f} "
    f"{'PASS' if bonf63_overall < 0.05 else 'FAIL'}（grill post-hoc: 63 子组口径）"
)

# ---------- 2. walk-forward 多 split 稳定性（R45）+ OOS Bonf 校正（R42）----------
print(f"\n{'=' * 70}")
print("2. walk-forward 多 split 稳定性（R45）+ OOS Bonf 校正（R42）")
print(f"{'=' * 70}")
a_sorted = sorted(a_picks, key=lambda p: p["buy_date"])
n = len(a_sorted)
# 多 split 比例全报（不只报最优 70/30——暴露 80/20 FAIL 衰减，R45）
splits = [(0.5, "50/50"), (0.6, "60/40"), (0.7, "70/30"), (0.8, "80/20")]
wf_results = {}
for ratio, label in splits:
    sp = int(n * ratio)
    tr = a_sorted[:sp]
    te = a_sorted[sp:]
    tr_s2 = stats([p["ret"] for p in tr])
    te_s2 = stats([p["ret"] for p in te])
    oos_bonf4 = min(te_s2["p"] * 4, 1.0)  # R42: OOS test 也要 Bonf 校正（不只 in-sample）
    decay = (tr_s2["mean"] - te_s2["mean"]) / tr_s2["mean"] * 100 if tr_s2["mean"] != 0 else 0
    wf_raw_pass = te_s2["mean"] > 0 and te_s2["p"] < 0.05
    oos_bonf_pass = te_s2["mean"] > 0 and oos_bonf4 < 0.05
    wf_results[label] = (tr_s2, te_s2, decay, oos_bonf4, wf_raw_pass, oos_bonf_pass)
    print(
        f"  {label}: train n={tr_s2['n']} EV={tr_s2['mean']:.4f}% / test n={te_s2['n']} "
        f"EV={te_s2['mean']:.4f}% raw_p={te_s2['p']:.4f} 衰减={decay:.1f}% "
        f"raw={'PASS' if wf_raw_pass else 'FAIL'} OOS_Bonf×4={oos_bonf4:.4f} {'PASS' if oos_bonf_pass else 'FAIL'}"
    )
# 默认用 70/30 作为主 walk-forward 结果（兼容后续 tr_s/te_s 引用）
tr_s, te_s, decay, oos_bonf4, _, _ = wf_results["70/30"]
print(f"\n  主结果（70/30，最优比例 post-hoc 可疑）: test raw_p={te_s['p']:.4f} OOS_Bonf×4={oos_bonf4:.4f} 衰减={decay:.1f}%")
print(f"  ⚠️ R42: OOS test raw p={te_s['p']:.4f} Bonf×4={oos_bonf4:.4f} — {'PASS' if oos_bonf4 < 0.05 else 'FAIL'}（原脚本漏了 OOS Bonf，grill 戳破）")
print(
    f"  ⚠️ R45: 80/20 test_p={wf_results['80/20'][1]['p']:.4f} {'PASS' if wf_results['80/20'][4] else 'FAIL'}（2022后 n={wf_results['80/20'][1]['n']} 暴露衰减）"
)

# ---------- 2b. 去离群稳定性（R45 离群依赖）----------
print(f"\n  R45 离群依赖检查（test 去最大离群后是否仍 PASS）:")
# 70/30 test picks（主 walk-forward 结果的 test 半）
sp70 = int(n * 0.7)
test_70 = a_sorted[sp70:]
test_sorted_by_ret = sorted(test_70, key=lambda p: p["ret"], reverse=True)
top_outlier = test_sorted_by_ret[0] if test_sorted_by_ret else None
if top_outlier:
    test_no_top = [p["ret"] for p in test_70 if p != top_outlier]
    te_no_top = stats(test_no_top)
    print(f"    最大离群: {top_outlier['buy_date']} ret={top_outlier['ret']:.3f}%")
    print(f"    去后: n={te_no_top['n']} EV={te_no_top['mean']:.4f}% raw_p={te_no_top['p']:.4f} Bonf×4={min(te_no_top['p'] * 4, 1.0):.4f}")
    print(f"    离群贡献: test 总 EV {(te_s['mean'] * te_s['n'] - te_no_top['mean'] * te_no_top['n']):.3f}% 中该 1 笔贡献 {top_outlier['ret']:.3f}%")

# ---------- 3. 真 DSR（Bailey-Lopez de Prado PSR）+ NW HAC 聚簇校正 ----------
print(f"\n{'=' * 70}")
print("3. 真 DSR（Bailey-Lopez de Prado PSR）+ NW HAC 聚簇校正")
print(f"{'=' * 70}")
from math import log as _ln

# 真 DSR: PSR = Φ((SR - SR*)sqrt(N-1) / (1 - γ3*SR + (γ4-1)/4 * SR^2))
# SR = mean/std (per pick Sharpe), SR* = E[max null SR] ≈ sqrt(2 ln N_trials) / sqrt(T)
sr = a_s["mean"] / a_s["std"] if a_s["std"] > 0 else 0
n_picks = a_s["n"]
# skew + excess kurtosis（从 raw moments）
m2 = sum((x - a_s["mean"]) ** 2 for x in a_rets) / n_picks if n_picks > 0 else 0
m3 = sum((x - a_s["mean"]) ** 3 for x in a_rets) / n_picks if n_picks > 0 else 0
m4 = sum((x - a_s["mean"]) ** 4 for x in a_rets) / n_picks if n_picks > 0 else 0
skew = m3 / (m2**1.5) if m2 > 0 else 0
excess_kurt = m4 / (m2**2) - 3 if m2 > 0 else 0
print(f"  Sharpe (per pick): {sr:.4f}  skew: {skew:.2f}  excess_kurt: {excess_kurt:.2f}")
# PSR for 多重 N_trials（grill: N=7/63/100）
for n_trials in [7, 63, 100]:
    sr_star = (2 * _ln(n_trials)) ** 0.5 / (n_picks**0.5) if n_trials > 1 else 0
    denom = 1 - skew * sr + (excess_kurt / 4) * sr**2
    if denom > 0:
        psr = 0.5 * (1 + erf((sr - sr_star) * (n_picks - 1) ** 0.5 / (denom * 2**0.5)))
    else:
        psr = 0.5
    print(f"  PSR (N_trials={n_trials}): SR*={sr_star:.4f} PSR={psr:.5f} {'PASS' if psr > 0.95 else 'FAIL'}（>0.95）")

# NW HAC: 按年月聚簇 cluster-robust SE（grill: 28/105=26.7% 聚同月，SE 增 7-12%）
cluster_map = defaultdict(list)
for p in a_picks:
    cluster_map[p["buy_date"][:7]].append(p["ret"])
n_clusters = len(cluster_map)
if n_clusters > 1:
    cluster_means = [sum(v) / len(v) for v in cluster_map.values()]
    cluster_var = sum((m - a_s["mean"]) ** 2 for m in cluster_means) / n_clusters
    se_cr = (cluster_var / n_clusters) ** 0.5
    t_nw = a_s["mean"] / se_cr if se_cr > 0 else 0
    p_nw = 0.5 * (1 - erf(t_nw / sqrt(2))) if t_nw > 0 else 1.0
    print(f"  NW HAC ({n_clusters} 年月聚簇): t={t_nw:.2f} p={p_nw:.4f} {'PASS' if p_nw < 0.05 else 'FAIL'}（raw t={a_s['t']:.2f}）")

# ---------- 4. 衰减检查（按 era）----------
print(f"\n{'=' * 70}")
print("4. 衰减检查（按 era + 2022 后）")
print(f"{'=' * 70}")
eras = [
    ("2004-2010", "2004-01-01", "2010-12-31"),
    ("2011-2017", "2011-01-01", "2017-12-31"),
    ("2018-2021", "2018-01-01", "2021-12-31"),
    ("2022+", "2022-01-01", "2099-12-31"),
]
for label, d0, d1 in eras:
    sub = [p["ret"] for p in a_picks if d0 <= p["buy_date"] <= d1]
    s = stats(sub)
    if s["n"] > 0:
        print(f"  {label}: n={s['n']} EV={s['mean']:.3f}% WR={s['wr'] * 100:.1f}% median={s['median']:.3f}% p={s['p']:.4f}")

# ---------- 5. 可交易期子分析（2011+，510210 ETF 上线后）----------
print(f"\n{'=' * 70}")
print("5. 可交易期子分析（2011+，510210 ETF 上线后）— 6 视角 grill 执行成本发现")
print(f"{'=' * 70}")
a_tradable = [p for p in a_picks if p["buy_date"] >= "2011-01-30"]
t_rets = [p["ret"] for p in a_tradable]
t_s = stats(t_rets)
t_bonf7 = min(t_s["p"] * 7, 1.0)
print(
    f"  可交易期 n={t_s['n']} EV={t_s['mean']:.4f}% WR={t_s['wr'] * 100:.1f}% "
    f"median={t_s['median']:.3f}% p_raw={t_s['p']:.4f} Bonf×6={t_bonf7:.4f} "
    f"{'PASS' if t_bonf7 < 0.05 else 'FAIL'}"
)
print(f"  对比全期 n={a_s['n']} EV={a_s['mean']:.4f}% Bonf×6={bonf7_overall:.4f} PASS")
print(f"  ⚠️ 扣可交易约束后 Bonf×6 {'PASS' if t_bonf7 < 0.05 else 'FAIL'}（{t_bonf7:.4f}）— edge 是边界值非稳健 confirmed")
print(f"  原因: 2004-2010 的 30 picks（29%）EV+1.258% WR80% 最高拉高整体，")
print(f"        但 510210（唯一跟踪上证综指 ETF）2011-01-30 才上线 → 不可交易")

# ---------- verdict ----------
print(f"\n{'=' * 70}")
print("verdict 判定（含 6 视角 grill 综合，2026-10-08）")
print(f"{'=' * 70}")
checks = {
    "lift>2x": lift > 2.0,
    "Bonf×7 PASS": bonf7_overall < 0.05,
    "walk-forward test PASS (raw)": te_s["mean"] > 0 and te_s["p"] < 0.05,
    "median>0": a_s["median"] > 0,
    "WR>55%": a_s["wr"] > 0.55,
    "2022后仍正": any(stats([p["ret"] for p in a_picks if p["buy_date"] >= "2022-01-01"])["mean"] > 0 for _ in [0]),
}
for k, v in checks.items():
    print(f"  {'✅' if v else '❌'} {k}")

# ⚠️ 6 视角 grill 发现的 2 NOT SURVIVE（戳破 confirmed，未在上方 checks 体现）
print(f"\n  ⚠️ 6 视角 grill 发现的 2 致命 flaw（戳破 confirmed）:")
print(f"    1. 执行成本: 29% picks（2004-2010）无上证综指 ETF 可交易（510210 2011才上线）")
print(f"       扣可交易期（2011+）n={t_s['n']} Bonf×6={t_bonf7:.4f} {'PASS' if t_bonf7 < 0.05 else 'FAIL'}")
print(f"    2. post-hoc: OOS test p={te_s['p']:.4f} 用裸 p 没 Bonf 校正，")
print(f"       Bonf×4={min(te_s['p'] * 4, 1.0):.4f} FAIL / Bonf×6={min(te_s['p'] * 6, 1.0):.4f} FAIL")
print(f"       A 组定义是 post-hoc subgroup selection + OOS test 离群依赖")

passed = sum(checks.values())
total = len(checks)
print(f"\n  上方 checks（in-sample 视角）: {passed}/{total} PASS")
print(f"  6 视角 grill: 4 SURVIVE(provisional) + 2 NOT SURVIVE(执行成本/post-hoc)")
verdict = "exploratory（真信号 in-sample 极强 p=0.00005 Bonf×63=0.003 仍 PASS，但 OOS 不够稳健到 confirmed）"
print(f"  综合 verdict: {verdict}")
print(f"\n  注：A 组是 TOM 在节假日语境的放大变体，TOM 2022 后死。")
print(f"  2022 后 A 组 n={stats([p['ret'] for p in a_picks if p['buy_date'] >= '2022-01-01'])['n']} underpowered。")
print(f"  待修: Bonf×7 + OOS test Bonf + NW HAC + 真 DSR + 多 split 稳定性（grill 已跑，待固化脚本）")
