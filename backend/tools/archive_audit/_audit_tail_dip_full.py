# -*- coding: utf-8 -*-
"""尾盘错杀低吸（tail-dip）walk-forward OOS + R12 + 跨 regime 全量验证。

背景：
  strategy4_backtest_result.md 用 3 个月缓存（2026-07~09, 2198 事件）得出"有效"
  结论（-10%stop+10%TP+5日 mean+0.72% WR52.2%）。但纯样本内、单期、无 OOS、
  stop 三选一挑最优（多重检验）、subgroup 甜区 post-hoc、lift 2.1× 卡噪声线且
  窗口错位（5日事件 vs 20日基准）。按项目 §44 v2/v3 + R42-R45 不达标。

本脚本：在 8 年 baostock 日 K 缓存上复现并严测：
  1. 全量 in-sample（复现报告口径，扩展到 8 年）
  2. walk-forward OOS（train 2018-2022 / test 2023-2026）
  3. 跨 regime（2018-2024 vs 2025-2026）
  4. R12 size-matched（同日同 amount-decile peers 中位 BHAR，alpha=event-peers）
  5. Bonferroni×N（nostop + 3 stop 档 = 4 配置多重校正）

信号定义（与 strategy4 报告一致，绝对跌幅代理）：
  - T0 close 跌幅 = close/prev_close - 1 < -3%（个股全天跌>3%）
  - 成交额 > 1e7，价格 2-80
  - 入场 T+1 open；nostop 出场 T+2 close；stop 出场 -10% stop / +10% TP / T+5 close

⚠️ 已知偏差（披露）：
  - 数据：791 只 8 年股 = inst_dominant backfill 的 LHB 上榜股子集（波动股偏差）。
    tail-dip 引擎产口径是全市场扫描，本测试 population ≠ 产 population。
    LHB 股波动更大 → 若在此子集上 edge 死，泛化到全市场更不可能；
    若在此子集上 edge 活，仍需全市场 backfill 复验（本次不做）。
  - 信号：本脚本测绝对跌幅>3%（报告验证的代理），引擎实际用板块相对偏离+量能收缩
    （calculate_anomalous_deviation），更严。代理信号是代理信号的超集，代理死≠
    严信号死，但代理活且严信号未测。严信号须另测（本次不做，待 population 解决）。
"""
import json
import sqlite3
import statistics
import bisect
from pathlib import Path
from collections import defaultdict
from math import erf

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vr_paths import resolve_data_dir


DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"

# 信号参数（strategy4 报告 §4.3 推荐口径）
MIN_DROP_PCT = -3.0      # close/prev_close - 1 < -3%
MIN_AMOUNT = 1e7         # 成交额 > 1000万
PRICE_LO = 2.0
PRICE_HI = 80.0
# 止损/止盈/持有（报告"最优"-10% 档）
STOPS = [-5.0, -8.0, -10.0]   # 三档 stop（报告测过，Bonf×N 校正用）
TP_PCT = 10.0
MAX_HOLD_DAYS = 5
# walk-forward 切分
TRAIN_END = "2022-12-31"
ALPHA = 0.05


def normal_p(t: float) -> float:
    return 2 * (1 - 0.5 * (1 + erf(abs(t) / (2 ** 0.5))))


def load_all_klines() -> list:
    """全市场 (code, bars) 一次载入，bars 已按 date 排序。"""
    conn = sqlite3.connect(str(KLINE_DB))
    rows = conn.execute("SELECT code, bars_json FROM kline").fetchall()
    conn.close()
    out: list = []
    for code, bj in rows:
        try:
            bars = sorted(json.loads(bj), key=lambda b: b.get("date", ""))
        except Exception:
            continue
        if bars:
            out.append((code, bars))
    return out


def detect_tail_dip_events(klines: list) -> list:
    """检测 tail-dip 事件：T0 close 跌幅>3% + 成交额>1e7 + 价格2-80。
    返回 [(event_date, code, t0_close, t1_idx, ...)]，t1_idx 是 T+1 bar 在 bars 中的索引。
    """
    events: list = []
    for code, bars in klines:
        n = len(bars)
        for i in range(1, n):
            prev_close = bars[i - 1].get("close")
            bar = bars[i]
            close = bar.get("close")
            amount = bar.get("amount", 0) or 0
            if not prev_close or prev_close <= 0 or not close:
                continue
            chg = (close / prev_close - 1) * 100
            if chg > MIN_DROP_PCT:  # 跌幅不够（MIN_DROP_PCT=-3，chg 需 <= -3）
                continue
            if chg < -20:  # 跌停一字板，买不到（R3 realizability）
                continue
            if amount < MIN_AMOUNT:
                continue
            if not (PRICE_LO <= close <= PRICE_HI):
                continue
            # 需要 T+1 (i+1) 存在才能入场
            if i + 1 >= n:
                continue
            events.append((bar.get("date", ""), code, i, bars))
    return events


def compute_nostop_return(bars: list, t0_idx: int) -> float | None:
    """T+1 open 买 → T+2 close 卖 nostop（1 日持有，与 inst_dominant nostop 同口径）。"""
    n = len(bars)
    if t0_idx + 2 >= n:
        return None
    t1_open = bars[t0_idx + 1].get("open")
    t2_close = bars[t0_idx + 2].get("close")
    if not t1_open or t1_open <= 0 or not t2_close:
        return None
    return (t2_close / t1_open - 1) * 100


def compute_stop_return(bars: list, t0_idx: int, stop_pct: float) -> float | None:
    """T+1 open 买，从 T+1 起 daily 检查 low≤stop / high≥TP，先触发者成交，否则 T+5 close。
    同日两者都满足 → 先止损（保守，与报告一致）。"""
    n = len(bars)
    entry_idx = t0_idx + 1
    if entry_idx >= n:
        return None
    entry = bars[entry_idx].get("open")
    if not entry or entry <= 0:
        return None
    stop_price = entry * (1 + stop_pct / 100)
    tp_price = entry * (1 + TP_PCT / 100)
    last_idx = min(entry_idx + MAX_HOLD_DAYS, n - 1)
    for j in range(entry_idx, last_idx + 1):
        low = bars[j].get("low")
        high = bars[j].get("high")
        hit_stop = low is not None and low <= stop_price
        hit_tp = high is not None and high >= tp_price
        if hit_stop and hit_tp:
            return (stop_price / entry - 1) * 100  # 先止损保守
        if hit_stop:
            return (stop_price / entry - 1) * 100
        if hit_tp:
            return (tp_price / entry - 1) * 100
    # 都没触发 → last_idx close
    exit_close = bars[last_idx].get("close")
    if not exit_close:
        return None
    return (exit_close / entry - 1) * 100


def stats_for(returns_by_date: dict, all_returns: list) -> dict:
    """day-clustered t 检验（同日多事件相关，按日均值算 t）。"""
    day_means = [statistics.mean(rs) for rs in returns_by_date.values() if rs]
    if len(day_means) < 2:
        return {}
    mean = statistics.mean(day_means)
    n_days = len(day_means)
    se = statistics.stdev(day_means) / (n_days ** 0.5) if n_days > 1 else 0
    t = mean / se if se > 0 else 0
    n = len(all_returns)
    wr = sum(1 for r in all_returns if r > 0) / n * 100 if n else 0
    sr = sorted(all_returns)
    median = sr[n // 2] if n else 0
    return {"n": n, "days": n_days, "mean": mean, "median": median, "wr": wr, "t": t, "p": normal_p(t)}


def collect_returns(events: list, mode: str, stop_pct: float = -10.0) -> tuple:
    """对 events 算前向收益，返回 (returns_by_date, all_returns)。"""
    rbd: dict = defaultdict(list)
    ar: list = []
    for date, code, t0_idx, bars in events:
        r = compute_nostop_return(bars, t0_idx) if mode == "nostop" else compute_stop_return(bars, t0_idx, stop_pct)
        if r is not None:
            rbd[date].append(r)
            ar.append(r)
    return rbd, ar


def report_block(label: str, rbd: dict, ar: list, bonf_n: int = 1) -> dict:
    s = stats_for(rbd, ar)
    if not s:
        print(f"  {label}: 数据不足")
        return {}
    p_bonf = min(1.0, s["p"] * bonf_n)
    v = "PASS" if p_bonf < ALPHA else "FAIL"
    print(f"  {label}: n={s['n']} days={s['days']} mean={s['mean']:.3f}% median={s['median']:.3f}% "
          f"WR={s['wr']:.1f}% day_t={s['t']:.2f} p={s['p']:.4f} Bonf×{bonf_n}={p_bonf:.4f} {v}")
    return {**s, "bonf": p_bonf, "verdict": v}


def compute_size_for_events(events: list) -> dict:
    """per event 20 日均成交额作为 size 代理（同 decile peers 匹配用）。"""
    date_code_size: dict = {}
    for date, code, t0_idx, bars in events:
        lo = max(0, t0_idx - 20)
        window = bars[lo:t0_idx]
        amts = [b.get("amount", 0) or 0 for b in window]
        if len(amts) >= 10:
            date_code_size[(date, code)] = sum(amts) / len(amts)
    return date_code_size


def compute_market_size_bhar(klines: list) -> tuple:
    """per-code 一次扫：每 (date, code) 的 20 日均额 + 同口径 nostop BHAR（T+1 open→T+2 close）。"""
    date_market: dict = defaultdict(list)
    for code, bars in klines:
        n = len(bars)
        amts = [b.get("amount", 0) or 0 for b in bars]
        opens = [b.get("open", 0) or 0 for b in bars]
        closes = [b.get("close", 0) or 0 for b in bars]
        dates = [b.get("date", "") for b in bars]
        wsum = 0.0
        window: list = []
        for i in range(n):
            window.append(amts[i])
            wsum += amts[i]
            if len(window) > 20:
                wsum -= window[0]
                window.pop(0)
            size = wsum / len(window) if len(window) >= 10 else None
            bhar = None
            if i + 2 < n and opens[i + 1] > 0:
                bhar = (closes[i + 2] / opens[i + 1] - 1) * 100
            if size is not None and bhar is not None:
                date_market[dates[i]].append((code, size, bhar))
    return date_market, klines


def r12_size_matched(events: list, date_market: dict) -> None:
    """R12: event stock BHAR - 同日同 amount-decile peers 中位 BHAR。alpha≈0 → size premium。"""
    event_size = compute_size_for_events(events)
    # per-date decile
    date_deciles: dict = {}
    date_peers: dict = {}
    for d, items in date_market.items():
        sizes = sorted(it[1] for it in items)
        n = len(sizes)
        if n < 10:
            continue
        deciles = [sizes[min(n - 1, n * i // 10)] for i in range(11)]
        date_deciles[d] = deciles
        peers_by_decile: list = [[] for _ in range(10)]
        for code, size, bhar in items:
            di = min(9, bisect.bisect_right(deciles, size) - 1)
            peers_by_decile[di].append((code, bhar))
        date_peers[d] = peers_by_decile

    alphas_by_date: dict = defaultdict(list)
    all_alphas: list = []
    matched = 0
    for date, code, t0_idx, bars in events:
        r = compute_nostop_return(bars, t0_idx)
        if r is None or (date, code) not in event_size:
            continue
        size = event_size[(date, code)]
        if date not in date_deciles:
            continue
        di = min(9, bisect.bisect_right(date_deciles[date], size) - 1)
        peers = date_peers[date][di]
        peers_bhar = [b for c, b in peers if c != code]
        if not peers_bhar:
            continue
        alpha = r - statistics.median(peers_bhar)
        alphas_by_date[date].append(alpha)
        all_alphas.append(alpha)
        matched += 1

    print(f"  R12 matched: {matched}/{len(events)}")
    if not all_alphas:
        print("  无 alpha 数据")
        return
    day_means = [statistics.mean(rs) for rs in alphas_by_date.values() if rs]
    mean = statistics.mean(day_means)
    n_days = len(day_means)
    se = statistics.stdev(day_means) / (n_days ** 0.5) if n_days > 1 else 0
    t = mean / se if se > 0 else 0
    n = len(all_alphas)
    wr = sum(1 for a in all_alphas if a > 0) / n * 100
    sr = sorted(all_alphas)
    median = sr[n // 2]
    p = normal_p(t)
    v = "PASS" if p < ALPHA and mean > 0 else "FAIL"
    print(f"  R12 alpha: n={n} days={n_days} mean_alpha={mean:.4f}% median={median:.4f}% "
          f"WR={wr:.1f}% day_t={t:.2f} p={p:.4f} {v}")
    print(f"  → {'size-matched edge（alpha 非 size premium）' if v == 'PASS' else 'alpha 被 size premium 解释 / underpowered'}")


def main() -> None:
    klines = load_all_klines()
    n_8yr = sum(1 for _, b in klines if len(b) >= 1900)
    print(f"=== tail-dip walk-forward OOS + R12 全量验证 ===")
    print(f"全市场 codes: {len(klines)} | 其中 >=8 年(1900 bars): {n_8yr}")
    print(f"信号: T0 跌幅<{MIN_DROP_PCT}% + 成交额>{MIN_AMOUNT:.0e} + 价格[{PRICE_LO},{PRICE_HI}]")
    print(f"入场 T+1 open；nostop 出场 T+2 close；stop 档 {STOPS} + TP {TP_PCT}% + {MAX_HOLD_DAYS} 日\n")

    events = detect_tail_dip_events(klines)
    n_8yr_events = sum(1 for e in events if len(e[3]) >= 1900)
    print(f"tail-dip 事件: {len(events)} | 其中 8 年股事件: {n_8yr_events}\n")

    # --- 1. 全量 in-sample（复现报告，扩展 8 年）---
    print("--- 1. 全量 in-sample（8 年）---")
    # Bonf×4 = nostop + 3 stop 档
    rbd_ns, ar_ns = collect_returns(events, "nostop")
    report_block("nostop (T+1open→T+2close)", rbd_ns, ar_ns, bonf_n=4)
    for sp in STOPS:
        rbd, ar = collect_returns(events, "stop", sp)
        report_block(f"stop {sp}% +TP{TP_PCT}% +5d", rbd, ar, bonf_n=4)
    print()

    # --- 2. walk-forward OOS（报告"最优"-10% 档）---
    print("--- 2. walk-forward OOS（-10% stop +10% TP +5d，报告最优档）---")
    train = [e for e in events if e[0] <= TRAIN_END]
    test = [e for e in events if e[0] > TRAIN_END]
    print(f"train: 2018-{TRAIN_END} ({len(train)} 事件) | test: {TRAIN_END}后-2026 ({len(test)} 事件)")
    train_rbd, train_ar = collect_returns(train, "stop", -10.0)
    test_rbd, test_ar = collect_returns(test, "stop", -10.0)
    train_s = report_block("train", train_rbd, train_ar, bonf_n=1)
    test_s = report_block("test", test_rbd, test_ar, bonf_n=4)  # test Bonf×4（4 配置）
    if train_s and test_s:
        gates = {
            "train_mean>0": train_s["mean"] > 0,
            "test_mean>0": test_s["mean"] > 0,
            "test_p<0.05": test_s["p"] < 0.05,
            "test_bonf4<0.05": test_s["bonf"] < 0.05,
            "train_test同方向": (train_s["mean"] > 0) == (test_s["mean"] > 0),
        }
        print("  walk-forward gate:")
        for g, v in gates.items():
            print(f"    {g}: {'PASS' if v else 'FAIL'}")
        all_pass = all(gates.values())
        print(f"\n  → walk-forward OOS verdict: {'edge-confirmed' if all_pass else 'NOT confirmed'}\n")

    # --- 3. 跨 regime（-10% 档）---
    print("--- 3. 跨 regime（-10% stop，2018-2024 vs 2025-2026）---")
    for regime, sub in [("2018-2024", [e for e in events if e[0] < "2025"]),
                        ("2025-2026", [e for e in events if e[0] >= "2025"])]:
        rbd, ar = collect_returns(sub, "stop", -10.0)
        report_block(regime, rbd, ar, bonf_n=2)
    print()

    # --- 4. R12 size-matched（nostop BHAR，与 inst_dominant R12 同口径）---
    print("--- 4. R12 size-matched（nostop BHAR vs 同日同 decile peers）---")
    date_market, _ = compute_market_size_bhar(klines)
    print(f"  全市场 (date,code) 有 size+bhar: {sum(len(v) for v in date_market.values())} | 日期数: {len(date_market)}")
    r12_size_matched(events, date_market)
    print()

    # --- 5. 最终判定 ---
    print("=== 最终判定 ===")
    print("⚠️ population=791 LHB 偏差股子集 + 信号=绝对跌幅代理（非引擎板块相对+量能）")
    print("以上任一 FAIL → 报告'有效'结论在本口径下不成立；全 PASS → 仍须全市场 backfill 复验")


if __name__ == "__main__":
    main()
