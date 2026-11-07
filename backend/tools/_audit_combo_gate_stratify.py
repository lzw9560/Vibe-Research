# -*- coding: utf-8 -*-
"""门判别力分层独立复现（2026-10-27）。

16-agent 对抗 workflow 的承重未验证数字：grill 报 gate=OFF t=7.46
（ON+3.28% > OFF+1.91% 有梯度），synthesis 没独立复现。本脚本独立跑。

口径：
- combo-5d-edge（R4 真 edge 口径）：composite = rank(gap)+rank(tr)+rank(-amount)，
  top-20，去涨停（主板9.8%/创科19.8%/北交29.8%），持5日 close→close（T收盘→T+5收盘）
- gate：breadth = 全市场 >60MA 占比；小盘组 = amount 排序最低 20%（amount-decile 代理，
  因 turn 2024前为0，cap 算不出）；sm5 = 小盘组 5d ret 均值；viable = breadth>0.4 and sm5>0

⚠️ 口径差异（诚实标注）：
1. 小盘分组：生产 monitor 用 cap-decile（turn 反推），本脚本用 amount-decile（成交额代理）。
   amount-decile = 低成交额 = 流动性差的小盘代理，≠ 流通市值小。相关但不等同。
   → 记一笔多重检验膨胀（这是第 2 种小盘口径）
2. combo 持有收益：close→close 5日（R4 口径），非 live T+1开买。和 grill 数字可比性假设它也用 close→close
3. grill 的 t=7.46 来源不明（现有 _audit_combo*.py 无 gate/breadth 实现），口径可能不同
4. 2024-2026 子集额外跑 cap-decile 对照，看 amount-decile 代理是否扭曲

判定：
- gate=OFF 仍 t>2 且 mean>0 → 门是梯度非 kill switch → combo 该梯度加权（OFF 用 0.3-0.5）
- gate=OFF 不显著 → 门是 kill switch（combo 只在门开时有效）

方法论底线（CLAUDE.md §1.2 + §44 v3）：
- 禁 post-hoc 调阈值（breadth>0.4 是 monitor 定的，不事后调）
- NW-t 自相关校正（日级收益 + 5日持有重叠 → 自相关强，lag≥5）
- 不外推（门分层是诊断非自动开关，命题A已证伪自动开关形态）
"""

from __future__ import annotations
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


DB = resolve_data_dir() / "baostock_kline_cache.db"
COST = 0.004  # 双边 0.4%（和 R4 一致）


def board_threshold(code: str) -> float:
    if code.startswith(("30", "68")):
        return 0.198
    if code.startswith(("8", "920", "9")):
        return 0.298
    return 0.098


def build_by_date() -> dict:
    """每日每票 {code, gap, tr, amt, fwd5, is_zt, above60, ret5, turn, cap}。

    above60 = c > ma60（breadth 用）
    ret5 = (c - bars[i-5].close)/bars[i-5].close（小盘组 sm5 用）
    cap = vol/(turn/100)*c/1e8（turn>0 时才算，2024-2026 子集对照用）
    ma60 用前缀和 O(1)（500万 bar × O(60) 太慢）
    """
    conn = sqlite3.connect(str(DB))
    rows = conn.execute("SELECT code, bars_json FROM kline").fetchall()
    conn.close()
    by_date: dict = defaultdict(list)
    for code, bj in rows:
        try:
            bars = sorted(json.loads(bj), key=lambda b: b.get("date", ""))
        except Exception:
            continue
        if len(bars) < 70:
            continue
        dates = [b.get("date", "") for b in bars]
        closes = [float(b.get("close", 0) or 0) for b in bars]
        opens = [float(b.get("open", 0) or 0) for b in bars]
        amts = [float(b.get("amount", 0) or 0) for b in bars]
        vols = [float(b.get("volume", 0) or 0) for b in bars]
        turns = [float(b.get("turn", 0) or 0) for b in bars]
        prefix = [0.0]
        for c in closes:
            prefix.append(prefix[-1] + c)
        thr = board_threshold(code)
        for i in range(60, len(bars) - 5):
            prev_c = closes[i - 1]
            prev5_c = closes[i - 5]
            o, c, amt, vol, turn = opens[i], closes[i], amts[i], vols[i], turns[i]
            if not prev_c or not c or not o or not amt:
                continue
            nc = closes[i + 5]
            if not nc:
                continue
            ma60 = (prefix[i] - prefix[i - 60]) / 60.0
            if not ma60:
                continue
            today_ret = (c - prev_c) / prev_c
            ret5 = (c - prev5_c) / prev5_c if prev5_c else 0.0
            cap = (vol / (turn / 100)) * c / 1e8 if turn else 0.0
            by_date[dates[i]].append(
                {
                    "code": code,
                    "gap": (o - prev_c) / prev_c,
                    "tr": today_ret,
                    "amt": amt,
                    "fwd5": (nc - c) / c,
                    "is_zt": today_ret >= thr,
                    "above60": c > ma60,
                    "ret5": ret5,
                    "cap": cap,
                }
            )
    return by_date


def gate_signal(lst: list, small_key: str = "amt") -> tuple[float, float, bool]:
    """返回 (breadth, sm5, viable)。small_key='amt'(代理) 或 'cap'(2024+对照)。"""
    n = len(lst)
    if not n:
        return 0.0, 0.0, False
    breadth = sum(1 for x in lst if x["above60"]) / n
    # 小盘组 = small_key 排序最低 20%（decile0-1），要求该字段非0
    eligible = [x for x in lst if x[small_key] > 0]
    if len(eligible) < n // 5:
        return breadth, 0.0, False
    eligible.sort(key=lambda x: x[small_key])
    small = eligible[: len(eligible) // 5]
    sm5 = statistics.mean(x["ret5"] for x in small)
    viable = breadth > 0.4 and sm5 > 0
    return breadth, sm5, viable


def combo_top20_nozt_fwd5(lst: list) -> float | None:
    """combo top-20 去涨停，返回当日 fwd5 均值（去涨停后<10 跳过 → None）。"""
    n = len(lst)
    if n < 200:
        return None
    sg = sorted(range(n), key=lambda k: lst[k]["gap"])
    st = sorted(range(n), key=lambda k: lst[k]["tr"])
    sa = sorted(range(n), key=lambda k: lst[k]["amt"])
    rg = {o: r / n for r, o in enumerate(sg)}
    rt = {o: r / n for r, o in enumerate(st)}
    ra = {o: (1 - r / n) for r, o in enumerate(sa)}
    scored = sorted(range(n), key=lambda k: rg[k] + rt[k] + ra[k], reverse=True)
    picks = [lst[k] for k in scored[:20]]
    picks = [p for p in picks if not p["is_zt"]]
    if len(picks) < 10:
        return None
    return statistics.mean(p["fwd5"] for p in picks)


def nw_t(series: list, min_lag: int = 5) -> float:
    """Newey-West HAC t 统计量。min_lag≥5 因 5日持有重叠。"""
    n = len(series)
    if n < 5:
        return 0.0
    m = statistics.mean(series)
    gamma0 = statistics.pvariance(series)  # (1/n)Σ(x-m)²
    lag = max(min_lag, int(4 * (n / 100) ** (2 / 9)))
    lag = min(lag, n - 1)
    s = gamma0
    for l in range(1, lag + 1):
        cov = sum((series[t] - m) * (series[t + l] - m) for t in range(n - l)) / n
        w = 1 - l / (lag + 1)  # Bartlett 核
        s += 2 * w * cov
    if s <= 0:
        return 0.0
    se = (s / n) ** 0.5
    return m / se if se > 0 else 0.0


def group_stats(daily_means: list) -> dict:
    if not daily_means:
        return {"n": 0, "mean": 0.0, "median": 0.0, "wr": 0.0, "net": 0.0, "t": 0.0, "t_nw": 0.0}
    m = statistics.mean(daily_means)
    med = statistics.median(daily_means)
    wr = sum(1 for x in daily_means if x > 0) / len(daily_means)
    std = statistics.pstdev(daily_means) if len(daily_means) > 1 else 0
    se = std / (len(daily_means) ** 0.5) if daily_means else 0
    t_ols = m / se if se > 0 else 0
    return {
        "n": len(daily_means),
        "mean": m,
        "median": med,
        "wr": wr,
        "net": m - COST,
        "t": t_ols,
        "t_nw": nw_t(daily_means),
    }


def fmt(r: dict) -> str:
    if r["n"] == 0:
        return f"{'(n=0)':<46}"
    return (
        f"{r['mean'] * 100:>+8.4f}%{r['median'] * 100:>+8.4f}%{r['wr'] * 100:>6.1f}%"
        f"{r['net'] * 100:>+8.4f}%{r['t']:>6.2f}{r['t_nw']:>7.2f}{r['n']:>6}"
    )


def main() -> None:
    by_date = build_by_date()
    all_dates = sorted(by_date.keys())

    # 算每日 gate 信号（amount-decile 代理）+ combo fwd5
    rows_amt = []  # (date, breadth, sm5, viable, combo_fwd5)
    rows_cap = []  # 2024+ cap-decile 对照
    for d in all_dates:
        lst = by_date[d]
        if len(lst) < 200:
            continue
        b_a, sm5_a, viable_a = gate_signal(lst, "amt")
        fwd5 = combo_top20_nozt_fwd5(lst)
        if fwd5 is None:
            continue
        rows_amt.append((d, b_a, sm5_a, viable_a, fwd5))
        # cap 对照（要求当日 cap>0 的票够多，即 turn 有数据 → 2024+）
        cap_eligible = sum(1 for x in lst if x["cap"] > 0)
        if cap_eligible >= len(lst) * 0.8:
            b_c, sm5_c, viable_c = gate_signal(lst, "cap")
            rows_cap.append((d, b_c, sm5_c, viable_c, fwd5))

    print(f"=== 门判别力分层独立复现（combo top-20 去涨停 持5日）===")
    print(f"数据：{len(rows_amt)} 个交易日（{rows_amt[0][0]}~{rows_amt[-1][0]}），amount-decile 代理口径")
    print(f"cap-decile 对照：{len(rows_cap)} 日（{rows_cap[0][0]}~{rows_cap[-1][0]}，turn 有数据子集）\n")

    # 1. 8年全量 amount-decile
    on = [r[4] for r in rows_amt if r[3]]
    off = [r[4] for r in rows_amt if not r[3]]
    print("【1】8年全量（amount-decile 代理）")
    print(f"{'组':<10}{'mean':>10}{'median':>10}{'WR':>8}{'net':>10}{'t_ols':>7}{'t_nw':>7}{'n_days':>7}")
    print("-" * 64)
    print(f"{'gate=ON':<10}{fmt(group_stats(on))}")
    print(f"{'gate=OFF':<10}{fmt(group_stats(off))}")
    print(f"{'全量':<10}{fmt(group_stats([r[4] for r in rows_amt]))}")
    print()

    # 2. 分年
    print("【2】分年（amount-decile 代理，gate=ON vs OFF）")
    print(f"{'年份':<6}{'组':<8}{'mean':>10}{'t_nw':>7}{'WR':>7}{'n':>6}")
    print("-" * 50)
    for yr in ["2018", "2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026"]:
        yr_rows = [r for r in rows_amt if r[0].startswith(yr)]
        if not yr_rows:
            continue
        on_y = [r[4] for r in yr_rows if r[3]]
        off_y = [r[4] for r in yr_rows if not r[3]]
        rs_on = group_stats(on_y)
        rs_off = group_stats(off_y)
        print(f"{yr:<6}{'ON':<8}{rs_on['mean'] * 100:>+9.4f}%{rs_on['t_nw']:>7.2f}{rs_on['wr'] * 100:>6.1f}%{rs_on['n']:>6}")
        print(f"{'':<6}{'OFF':<8}{rs_off['mean'] * 100:>+9.4f}%{rs_off['t_nw']:>7.2f}{rs_off['wr'] * 100:>6.1f}%{rs_off['n']:>6}")
    print()

    # 3. cap-decile 对照（2024+，看 amount-decile 代理是否扭曲）
    if rows_cap:
        print("【3】cap-decile 对照（2024+ turn 有数据，看代理口径差异）")
        on_c = [r[4] for r in rows_cap if r[3]]
        off_c = [r[4] for r in rows_cap if not r[3]]
        print(f"{'组':<10}{'mean':>10}{'t_nw':>7}{'WR':>7}{'n':>6}")
        print("-" * 46)
        rc_on = group_stats(on_c)
        rc_off = group_stats(off_c)
        print(f"{'cap-ON':<10}{rc_on['mean'] * 100:>+9.4f}%{rc_on['t_nw']:>7.2f}{rc_on['wr'] * 100:>6.1f}%{rc_on['n']:>6}")
        print(f"{'cap-OFF':<10}{rc_off['mean'] * 100:>+9.4f}%{rc_off['t_nw']:>7.2f}{rc_off['wr'] * 100:>6.1f}%{rc_off['n']:>6}")
        # 同日期 amount-decile 对照
        cap_dates = {r[0] for r in rows_cap}
        on_a_match = [r[4] for r in rows_amt if r[0] in cap_dates and r[3]]
        off_a_match = [r[4] for r in rows_amt if r[0] in cap_dates and not r[3]]
        ra_on = group_stats(on_a_match)
        ra_off = group_stats(off_a_match)
        print(f"{'amt-ON*':<10}{ra_on['mean'] * 100:>+9.4f}%{ra_on['t_nw']:>7.2f}{ra_on['wr'] * 100:>6.1f}%{ra_on['n']:>6}")
        print(f"{'amt-OFF*':<10}{ra_off['mean'] * 100:>+9.4f}%{ra_off['t_nw']:>7.2f}{ra_off['wr'] * 100:>6.1f}%{ra_off['n']:>6}")
        print("  *amt 同日期子集对照 cap（看两口径在相同日判 gate 是否一致）")
        # gate 判定一致性
        amt_map = {r[0]: r[3] for r in rows_amt}
        cap_map = {r[0]: r[3] for r in rows_cap}
        common = set(amt_map) & set(cap_map)
        agree = sum(1 for d in common if amt_map[d] == cap_map[d])
        print(f"  gate 判定一致率：{agree}/{len(common)} = {agree / len(common) * 100:.1f}%")
        print()

    # 4. 判定
    print("【4】判定（amount-decile 8年全量）")
    rs_off_full = group_stats(off)
    if rs_off_full["n"] > 0:
        print(
            f"  gate=OFF: mean={rs_off_full['mean'] * 100:+.4f}% t_nw={rs_off_full['t_nw']:.2f} WR={rs_off_full['wr'] * 100:.1f}% n={rs_off_full['n']}"
        )
        if rs_off_full["t_nw"] > 2 and rs_off_full["mean"] > 0:
            print("  → ✅ 门是梯度非 kill switch（OFF 仍显著正）→ combo 该梯度加权（OFF 用 0.3-0.5）")
        elif rs_off_full["mean"] > 0 and rs_off_full["t_nw"] <= 2:
            print("  → ⚠️ 门偏梯度但 OFF 不显著（combo 在 OFF 弱正但不稳）→ 梯度加权要谨慎，OFF 用低权")
        else:
            print("  → ❌ 门是 kill switch（OFF 不显著或负）→ combo 只在门开时有效，OFF 该停")
    print()
    print("【5】caveat")
    print("  - amount-decile 代理 ≠ cap-decile（低成交额≠流通市值小），记多重检验膨胀")
    print("  - combo close→close 5日，非 live T+1开买口径")
    print("  - grill t=7.46 口径不明，本脚本 t_nw 用 NW 校正（≥5 lag），与 grill 数字若不一致可能是口径/校正差异")
    print("  - 前瞻验证必要：本回测是 in-sample 诊断，不构成自动开关依据（命题A已证伪自动开关）")


if __name__ == "__main__":
    main()
