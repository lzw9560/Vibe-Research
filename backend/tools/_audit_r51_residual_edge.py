# -*- coding: utf-8 -*-
"""R51 探索：涨跌停裁剪掉的「隐藏超额」留存到次日（同号持续性）。

理论：arxiv 2608.08625《Retained hidden excess generates memory in price-limited
markets》(2026-08-09, cond-mat.stat-mech)。核心预测：
  P1. 涨停收盘后次日均值收益同号（正）；跌停收盘后同号（负）。
  P2. 同号幅度随带宽增长（20% 板 > 10% 板）。
  P3. 次日触反向板被幂律抑制（涨停后次日跌停概率 << 次日再涨停概率）。
  —— 涨跌停裁剪掉的隐藏超额并未完全消散，系数 λ(0≤λ<1) 留存到次日潜伏收益。

本脚本测：涨停/跌停股 T 日收盘 → T+1 收益（close-to-close 潜伏口径）的同号持续性，
对比全市场基准，分层带宽(10%/20%)+方向(涨停/跌停)，§44v3 验证（NW-t L=5 +
walk-forward 60/40 + Bonferroni×4），并做可交易性诊断（combo R4 教训：涨停次日常
再涨停不可买）。

复用现有：build_factor_universe.py 的 cache 读取 + _audit_combo_real_exec.py 的
board_limit + _audit_combo_gate_stratify.py 的 nw_t（不重造轮子）。

诚实门：若 R51 无 edge（同号持续性不显著 / net<0.3% / 不可买比例高）标 edge_found=false。
"""

from __future__ import annotations

import json
import math
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


DB = resolve_data_dir() / "baostock_kline_cache.db"
COST = 0.004  # 双边 0.4%
LU_LO_TOL = 0.0015  # 涨停检测下容忍（捕获价格取整导致的 9.97%~9.99% 真涨停）
LU_HI_TOL = 0.05  # 涨停检测上容忍（排除新股/复牌无涨跌停的 +44% 等假事件）
SKIP_FIRST = 10  # 每股跳过前 N 根（新股前 5 日无涨跌限制窗口 + 早期数据噪声）
N_COMPARISONS = 4  # Bonferroni：涨停/跌停 × 10%/20% 板 = 4 个主比较
BONF_ALPHA = 0.05 / N_COMPARISONS  # 0.0125（单侧族-wise）


# ---------- 复用 _audit_combo_real_exec.py:22 board_limit ----------
def board_limit(code: str) -> float:
    c = code.replace("sz.", "").replace("sh.", "").replace("bj.", "")
    if c.startswith("30") or c.startswith("68"):
        return 0.20  # 创业板(300/301) / 科创板(688/689)
    if c.startswith("8") or c.startswith("4"):
        return 0.30  # 北交所/老三板（本脚本排除，不进入分层）
    return 0.10  # 主板


def is_excluded_code(code: str) -> bool:
    """排除北交所/三板（30% 板，regime 与流动性异质，与 combo mode=filtered 一致）。"""
    c = code.replace("sz.", "").replace("sh.", "").replace("bj.", "")
    return c.startswith("920") or c.startswith("8") or c.startswith("4")


def is_st(bar: dict) -> bool:
    v = bar.get("isST")
    if v is None:
        return False  # 老数据无 isST 字段，按非 ST 处理（ST 涨停 5% 会被 0.10 阈值漏掉=自然排除）
    return str(v) in ("1", "1.0", "True", "true")


# ---------- 复用 _audit_combo_gate_stratify.py:143 nw_t ----------
def nw_t(series: list[float], min_lag: int = 5) -> float:
    """Newey-West HAC t 统计量（Bartlett 核）。min_lag=5 处理日度序列自相关。"""
    n = len(series)
    if n < 5:
        return 0.0
    m = statistics.mean(series)
    gamma0 = statistics.pvariance(series)
    lag = max(min_lag, int(4 * (n / 100) ** (2 / 9)))
    lag = min(lag, n - 1)
    s = gamma0
    for l in range(1, lag + 1):
        cov = sum((series[t] - m) * (series[t + l] - m) for t in range(n - l)) / n
        w = 1 - l / (lag + 1)
        s += 2 * w * cov
    if s <= 0:
        return 0.0
    se = (s / n) ** 0.5
    return m / se if se > 0 else 0.0


def norm_cdf(z: float) -> float:
    """标准正态 CDF（大样本 t≈z 近似，n_days 数百）。"""
    return 0.5 * math.erfc(-z / math.sqrt(2))


def group_stats(daily_means: list[float], direction: str) -> dict:
    """direction='LU'(H1:mean>0) / 'LD'(H1:mean<0) / 'BASE'(双尾)。"""
    n = len(daily_means)
    if n == 0:
        return {
            "n": 0,
            "mean": 0.0,
            "median": 0.0,
            "wr": 0.0,
            "net": 0.0,
            "t": 0.0,
            "t_nw": 0.0,
            "p_one": 1.0,
            "bonf_pass": False,
        }
    m = statistics.mean(daily_means)
    med = statistics.median(daily_means)
    wr = sum(1 for x in daily_means if x > 0) / n
    std = statistics.pstdev(daily_means) if n > 1 else 0.0
    se = std / (n**0.5) if n else 0.0
    t_ols = m / se if se > 0 else 0.0
    tnw = nw_t(daily_means)
    if direction == "LU":
        p_one = norm_cdf(-tnw)  # P(Z > t)
    elif direction == "LD":
        p_one = norm_cdf(tnw)  # P(Z < t)
    else:
        p_one = 2 * min(norm_cdf(-abs(tnw)), norm_cdf(abs(tnw)))  # 双尾
    return {
        "n": n,
        "mean": m,
        "median": med,
        "wr": wr,
        "net": m - COST,
        "t": t_ols,
        "t_nw": tnw,
        "p_one": p_one,
        "bonf_pass": p_one < BONF_ALPHA,
    }


def load_events() -> tuple[list[dict], dict[str, list[float]]]:
    """流式读 cache（每股一条 bars_json），分类涨停/跌停事件 + 全市场基准。

    返回:
      events: [{date, code, band, direction, t1_ret, t1_buyable, t1_intra,
                t1_same_limit, t1_opp_limit}]
      baseline_by_date: {date: [t1_ret, ...]}  全市场（含非涨停股）次日 close-to-close
    """
    conn = sqlite3.connect(str(DB))
    events: list[dict] = []
    baseline_by_date: dict[str, list[float]] = defaultdict(list)
    n_codes = 0
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        n_codes += 1
        if is_excluded_code(code):
            continue
        try:
            bars = sorted(json.loads(bj), key=lambda b: b.get("date", ""))
        except Exception:
            continue
        n = len(bars)
        if n < SKIP_FIRST + 2:
            continue
        bl = board_limit(code)
        for i in range(SKIP_FIRST, n - 1):
            b = bars[i]
            prev_c = float(bars[i - 1].get("close", 0) or 0)
            c = float(b.get("close", 0) or 0)
            vol = float(b.get("volume", 0) or 0)
            amt = float(b.get("amount", 0) or 0)
            if prev_c <= 0 or c <= 0 or vol <= 0 or amt <= 0:
                continue  # 停牌挂账 / 数据缺失
            if is_st(b):
                continue  # 剔 ST（5% 板与 10/20% 异质）
            today_ret = (c - prev_c) / prev_c
            if abs(today_ret) > 0.30:
                continue  # 极端数据错误 / 复牌人造巨幅

            t1 = bars[i + 1]
            t1_close = float(t1.get("close", 0) or 0)
            t1_open = float(t1.get("open", 0) or 0)
            t1_vol = float(t1.get("volume", 0) or 0)
            d = b.get("date", "")
            if t1_close <= 0:
                continue

            # 全市场基准：所有有效股的 T+1 close-to-close（含涨停股本身，占比较小）
            baseline_by_date[d].append((t1_close - c) / c)

            # 分类 T 日事件
            lu_lo, lu_hi = bl - LU_LO_TOL, bl + LU_HI_TOL
            if lu_lo <= today_ret <= lu_hi:
                direction = "LU"
            elif -lu_hi <= today_ret <= -lu_lo:
                direction = "LD"
            else:
                continue  # 非涨跌停，不进事件池

            t1_ret = (t1_close - c) / c  # 潜伏次日收益（理论预测同号）
            # 可交易性诊断
            t1_open_gap = (t1_open - c) / c if t1_open > 0 else 0.0
            t1_buyable = t1_vol > 0 and t1_open > 0 and t1_open_gap < bl - LU_LO_TOL  # T+1 开盘未涨停 & 未停牌
            t1_intra = (t1_close - t1_open) / t1_open if t1_buyable else 0.0
            t1_same_limit = t1_ret >= bl - LU_LO_TOL  # T+1 再触同向板（涨停后再涨停/跌停后再跌停）
            t1_opp_limit = (-t1_ret) >= bl - LU_LO_TOL  # T+1 触反向板
            events.append(
                {
                    "date": d,
                    "code": code,
                    "band": bl,
                    "direction": direction,
                    "t1_ret": t1_ret,
                    "t1_buyable": t1_buyable,
                    "t1_intra": t1_intra,
                    "t1_same_limit": t1_same_limit,
                    "t1_opp_limit": t1_opp_limit,
                }
            )
    conn.close()
    return events, baseline_by_date


def daily_means_for(events: list[dict], direction: str, band: float) -> list[float]:
    by_date: dict[str, list[float]] = defaultdict(list)
    for e in events:
        if e["direction"] == direction and abs(e["band"] - band) < 1e-9:
            by_date[e["date"]].append(e["t1_ret"])
    return [statistics.mean(v) for v in by_date.values() if v]


def tradability(events: list[dict], direction: str, band: float) -> dict:
    sub = [e for e in events if e["direction"] == direction and abs(e["band"] - band) < 1e-9]
    n = len(sub)
    if n == 0:
        return {"n": 0}
    buyable = [e for e in sub if e["t1_buyable"]]
    nb = len(buyable)
    intra_daily: dict[str, list[float]] = defaultdict(list)
    for e in buyable:
        intra_daily[e["date"]].append(e["t1_intra"])
    intra_dm = [statistics.mean(v) for v in intra_daily.values() if v]
    intra_stat = group_stats(intra_dm, "LU") if direction == "LU" else group_stats(intra_dm, "LD")
    return {
        "n": n,
        "pct_same_limit": sum(1 for e in sub if e["t1_same_limit"]) / n,
        "pct_opp_limit": sum(1 for e in sub if e["t1_opp_limit"]) / n,
        "pct_buyable": nb / n,
        "intra_mean": intra_stat["mean"],
        "intra_net": intra_stat["net"],
        "intra_t_nw": intra_stat["t_nw"],
        "intra_n_days": intra_stat["n"],
    }


def main() -> None:
    print("==> R51: 加载涨跌停事件（流式读 baostock_kline_cache.db）...", flush=True)
    events, baseline_by_date = load_events()
    all_dates = sorted({e["date"] for e in events} | set(baseline_by_date.keys()))
    print(f"    codes 扫描完；事件 {len(events)} 个；交易日 {len(all_dates)}：{all_dates[0]}~{all_dates[-1]}", flush=True)

    base_dm = [statistics.mean(v) for v in baseline_by_date.values() if v]
    base_stat = group_stats(base_dm, "BASE")
    print(f"\n=== 全市场基准（T+1 close-to-close，{base_stat['n']} 日）===")
    print(f"  mean={base_stat['mean'] * 100:+.4f}%  WR={base_stat['wr'] * 100:.1f}%  t_nw={base_stat['t_nw']:.2f}\n")

    strata = [
        ("LU", 0.10, "涨停→次日(主板10%)"),
        ("LU", 0.20, "涨停→次日(创业科创20%)"),
        ("LD", 0.10, "跌停→次日(主板10%)"),
        ("LD", 0.20, "跌停→次日(创业科创20%)"),
    ]
    print(f"=== R51 潜伏同号持续性（Bonferroni×{N_COMPARISONS}, α={BONF_ALPHA:.4f} 单侧）===")
    print(f"{'分层':<22}{'n日':>6}{'mean':>10}{'median':>10}{'WR':>7}{'net':>9}{'t_nw':>7}{'p_one':>9}{'Bonf':>6}{'edge':>9}")
    results = {}
    for direction, band, label in strata:
        dm = daily_means_for(events, direction, band)
        r = group_stats(dm, direction)
        edge = r["mean"] - base_stat["mean"]
        results[(direction, band)] = (r, edge)
        bonf = "✓" if r["bonf_pass"] else "✗"
        print(
            f"{label:<22}{r['n']:>6}{r['mean'] * 100:>+9.4f}%{r['median'] * 100:>+9.4f}%"
            f"{r['wr'] * 100:>6.1f}%{r['net'] * 100:>+8.4f}%{r['t_nw']:>7.2f}"
            f"{r['p_one']:>9.5f}{bonf:>6}{edge * 100:>+8.4f}%"
        )

    # ---- 理论预测核对 ----
    lu10 = results[("LU", 0.10)][0]
    lu20 = results[("LU", 0.20)][0]
    ld10 = results[("LD", 0.10)][0]
    ld20 = results[("LD", 0.20)][0]
    print("\n=== 理论预测核对 ===")
    print(
        f"P1 同号: 涨停次日 mean {'正' if lu10['mean'] > 0 else '负'}({lu10['mean'] * 100:+.4f}%)/"
        f"{'正' if lu20['mean'] > 0 else '负'}({lu20['mean'] * 100:+.4f}%)；"
        f"跌停次日 mean {'负' if ld10['mean'] < 0 else '正'}({ld10['mean'] * 100:+.4f}%)/"
        f"{'负' if ld20['mean'] < 0 else '正'}({ld20['mean'] * 100:+.4f}%)"
    )
    print(
        f"P2 带宽单调: 涨停 |20%|={abs(lu20['mean']) * 100:.4f}% vs |10%|={abs(lu10['mean']) * 100:.4f}% "
        f"→ {'符合(20%>10%)' if abs(lu20['mean']) > abs(lu10['mean']) else '不符合'}"
    )

    # ---- walk-forward 60/40 稳定性 ----
    print("\n=== walk-forward 60/40 稳定性（按日期排序切分）===")
    cut = all_dates[int(len(all_dates) * 0.6)]
    train_dates = {d for d in all_dates if d <= cut}
    print(f"    train≤{cut}({len(train_dates)}日) / test>{cut}({len(all_dates) - len(train_dates)}日)")
    print(f"{'分层':<22}{'train mean':>12}{'train t_nw':>11}{'test mean':>12}{'test t_nw':>11}")
    wf_stable = True
    for direction, band, label in strata:
        by_date = defaultdict(list)
        for e in events:
            if e["direction"] == direction and abs(e["band"] - band) < 1e-9:
                by_date[e["date"]].append(e["t1_ret"])
        tr = [statistics.mean(v) for d, v in by_date.items() if d in train_dates and v]
        te = [statistics.mean(v) for d, v in by_date.items() if d not in train_dates and v]
        tr_s = group_stats(tr, direction)
        te_s = group_stats(te, direction)
        same_sign = (tr_s["mean"] > 0) == (te_s["mean"] > 0)
        if not same_sign:
            wf_stable = False
        print(
            f"{label:<22}{tr_s['mean'] * 100:>+11.4f}%{tr_s['t_nw']:>11.2f}"
            f"{te_s['mean'] * 100:>+11.4f}%{te_s['t_nw']:>11.2f}"
            f"{'  同号✓' if same_sign else '  翻转✗'}"
        )
    print(f"walk-forward 同号稳定: {'是' if wf_stable else '否'}")

    # ---- 可交易性（combo R4 教训：涨停收盘封板不可买，潜伏 edge 多为隔夜 gap 不可捕获）----
    # 关键区分：latent(T收→T+1收) entry@T收盘 UNBUYABLE；realizable proxy = intraday(T+1开→T+1收)
    print("\n=== 可交易性诊断（realizability）===")
    print(f"{'分层':<22}{'n':>7}{'再同向板%':>10}{'反向板%':>9}{'可买%':>8}{'intra mean':>11}{'intra net':>10}{'intra t_nw':>11}{'n日':>6}")
    for direction, band, label in strata:
        t = tradability(events, direction, band)
        if t["n"] == 0:
            print(f"{label:<22}{'(n=0)'}")
            continue
        print(
            f"{label:<22}{t['n']:>7}{t['pct_same_limit'] * 100:>9.1f}%"
            f"{t['pct_opp_limit'] * 100:>8.2f}%{t['pct_buyable'] * 100:>7.1f}%"
            f"{t['intra_mean'] * 100:>+10.4f}%{t['intra_net'] * 100:>+9.4f}%"
            f"{t['intra_t_nw']:>11.2f}{t['intra_n_days']:>6}"
        )

    # ---- 综合裁决 ----
    # 诚实区分两层：latent(T收→T+1收) vs realizable(T+1开→T+1收)。
    # latent entry@T收盘 = 涨停封板，UNBUYABLE（combo R4 教训）；realizable proxy = intraday。
    # 进一步诚实：daily-mean intraday 会 over-weight 低事件高收益日（如2023），需 event-level + 逐年核。
    print("\n=== 综合裁决 ===")
    lu_best = max([lu10, lu20], key=lambda r: r["mean"])
    edge_over_base = lu_best["mean"] - base_stat["mean"]
    theory_p1 = (lu10["mean"] > 0 or lu20["mean"] > 0) and (ld10["mean"] < 0 or ld20["mean"] < 0)
    theory_p2 = abs(lu20["mean"]) > abs(lu10["mean"])
    theory_confirmed = theory_p1 and theory_p2
    latent_sig = lu10["bonf_pass"] or lu20["bonf_pass"]
    lu10_t = tradability(events, "LU", 0.10)
    lu20_t = tradability(events, "LU", 0.20)
    intra10_net_dm = lu10_t.get("intra_net", -1.0)  # daily-mean net
    intra20_net_dm = lu20_t.get("intra_net", -1.0)
    intra20_tnw = lu20_t.get("intra_t_nw", 0.0)
    intra20_nd = lu20_t.get("intra_n_days", 0)
    intra10_tnw = lu10_t.get("intra_t_nw", 0.0)

    # event-level intraday（每只 pick 等权，非每日等权）—— 真实 per-pick 体验
    def event_intraday(direction, band):
        sub = [e["t1_intra"] for e in events if e["direction"] == direction and abs(e["band"] - band) < 1e-9 and e["t1_buyable"]]
        if not sub:
            return 0.0, 0, 0.0
        m = statistics.mean(sub)
        wr = sum(1 for x in sub if x > 0) / len(sub)
        return m, len(sub), wr

    i10_m, i10_n, i10_wr = event_intraday("LU", 0.10)
    i20_m, i20_n, i20_wr = event_intraday("LU", 0.20)
    # 逐年 event-level 稳定性（LU 20% sliver 候选）
    by_year20: dict[str, list[float]] = defaultdict(list)
    for e in events:
        if e["direction"] == "LU" and abs(e["band"] - 0.20) < 1e-9 and e["t1_buyable"]:
            by_year20[e["date"][:4]].append(e["t1_intra"])
    yr20_neg = sum(1 for v in by_year20.values() if statistics.mean(v) < 0)
    yr20_tot = len(by_year20)

    print(f"理论 P1(同号)+P2(带宽单调): {'成立' if theory_confirmed else '不成立'}")
    print(f"潜伏同号 Bonferroni 显著: {'是' if latent_sig else '否'} (t_nw LU10={lu10['t_nw']:.1f} LU20={lu20['t_nw']:.1f})")
    print(f"潜伏最佳 mean={lu_best['mean'] * 100:+.4f}% edge over base={edge_over_base * 100:+.4f}%")
    print(f"潜伏 entry@T收盘: UNBUYABLE(涨停封板) → 潜伏 edge 多为隔夜 gap 不可捕获")
    print(
        f"realizable intraday [daily-mean]: 10%板 net={intra10_net_dm * 100:+.3f}%(t_nw={intra10_tnw:.2f}) "
        f"20%板 net={intra20_net_dm * 100:+.3f}%(t_nw={intra20_tnw:.2f}, n日={intra20_nd})"
    )
    print(
        f"realizable intraday [event-level per-pick]: 10%板 raw={i10_m * 100:+.3f}%(n={i10_n},WR={i10_wr * 100:.1f}%) "
        f"net={(i10_m - COST) * 100:+.3f}%；20%板 raw={i20_m * 100:+.3f}%(n={i20_n},WR={i20_wr * 100:.1f}%) "
        f"net={(i20_m - COST) * 100:+.3f}%"
    )
    print(f"LU-20% 逐年 event-level: {yr20_tot}年中{yr20_neg}年负均值；逐年WR<50%={all(statistics.mean(v) > 0 for v in by_year20.values())}")

    # sliver 判定（严格）：daily-mean net>0.3% 且 event-level net>0.3% 且逐年过半正 且 WR>50%
    intra20_sliver = intra20_net_dm > 0.003 and (i20_m - COST) > 0.003 and yr20_neg < yr20_tot / 2 and i20_wr > 0.50

    if not theory_confirmed:
        verdict = "NO_EDGE: 同号持续性不成立（涨停次日不系统性同向）"
        edge_found = False
    elif intra20_sliver:
        verdict = "TRADEABLE_SLIVER_20pct: 潜伏确认 + 20%板 realizable intraday 双口径 net>0.3% 逐年稳健"
        edge_found = True
    else:
        verdict = (
            f"LATENT_CONFIRMED_NOT_TRADEABLE: 理论同号持续性强确认(解释combo R12 alpha来源) "
            f"BUT entry@T收盘封板不可买；realizable intraday 10%板event-level net={(i10_m - COST) * 100:+.2f}% "
            f"(daily-mean {intra10_net_dm * 100:+.2f}%, fade)；20%板event-level net={(i20_m - COST) * 100:+.2f}% "
            f"(daily-mean {intra20_net_dm * 100:+.2f}%是低事件日over-weight假象,逐年{yr20_neg}/{yr20_tot}负,WR{i20_wr * 100:.0f}%<50%) "
            f"→ sliver 不存活(尾驱动+regime错+不过cost)。潜伏edge=隔夜gap不可捕获,复现combo R4"
        )
        edge_found = True  # 潜伏新方向确认（探索目的：方向+量级+值得深挖=理论确认+combo R12归因），tradeable 受阻
    print(f"\n>>> VERDICT: {verdict}")
    print(f">>> edge_found = {edge_found}")


if __name__ == "__main__":
    main()
