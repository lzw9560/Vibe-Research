# -*- coding: utf-8 -*-
"""explore_capitulation_bounce.py

capitulation-bounce 反弹检测器（10-29 combo live +3.67% WR90% 正种子，唯一未测正信号）。
不同类别=market timing + 反弹捕获 vs 已证伪的因子选股。

信号设计（待 workflow 专家校准）：
- 极端恐慌日 D：breadth<5%（<5%股上涨）OR 跌停数>阈值 OR 小盘5日跌幅>阈值
- 反弹触发：D+k 日 breadth 转正（>50%）OR 小盘 Δsm5 转正
- 买入：反弹触发日买小盘/超跌股（或指数 ETF 等权）
- 持有 N 天测 return

本步：算 market breadth + 跌停 + 涨停 + 小盘等权时序（基础数据）。
从 kline cache 全市场一次 pass（5255 股 × ~2000 天）。
"""
from __future__ import annotations
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir  # noqa: E402

DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
BREADTH_DB = DATA / "market_breadth.db"  # 新建


def board_limit(code: str) -> float:
    c = code.replace("sz.", "").replace("sh.", "").replace("bj.", "")
    if c.startswith(("30", "68")):
        return 0.20
    if c.startswith(("4", "8")):
        return 0.30
    return 0.10


def compute_breadth_series() -> dict:
    """全市场一次 pass：每日 涨/跌/涨停/跌停 家数 + 小盘等权收益。
    返回 {date: {adv, dec, limit_up, limit_down, total, smallcap_eq_ret}}.
    小盘 = 流通市值最低 500 股等权（用 avg amount 代理，最低 amount 500 股作 smallcap proxy）。
    """
    conn = sqlite3.connect(str(KLINE_DB))
    # 先算每股 avg amount 定 smallcap universe
    code_avg_amt: dict[str, float] = {}
    code_bars: dict[str, list] = {}
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list) or len(bars) < 200:
            continue
        amts = [float(b.get("amount", 0) or 0) for b in bars if b.get("amount")]
        if amts:
            code_avg_amt[code] = sum(amts) / len(amts)
            code_bars[code] = bars
    conn.close()
    # smallcap = 最低 amount 500 股（小盘流动性低=小盘 proxy）
    sorted_by_amt = sorted(code_avg_amt.items(), key=lambda x: x[1])
    smallcap_codes = {c for c, _ in sorted_by_amt[:500]}
    print(f"universe: {len(code_bars)} stocks, smallcap(bottom-500 amount): {len(smallcap_codes)}")

    # 每日聚合
    daily: dict[str, dict] = defaultdict(lambda: {"adv": 0, "dec": 0, "flat": 0, "limit_up": 0, "limit_down": 0, "total": 0, "sc_rets": []})
    for code, bars in code_bars.items():
        bl = board_limit(code)
        prev_close = None
        for b in bars:
            d = b.get("date", "")
            if not d:
                continue
            c = b.get("close")
            try:
                c = float(c) if c else None
            except (ValueError, TypeError):
                c = None
            if c is None or c <= 0:
                continue
            if prev_close and prev_close > 0:
                ret = (c - prev_close) / prev_close
                dd = daily[d]
                dd["total"] += 1
                if ret > 0.0001:
                    dd["adv"] += 1
                elif ret < -0.0001:
                    dd["dec"] += 1
                else:
                    dd["flat"] += 1
                # 涨停/跌停（接近 limit，qfq return 经济回报正确）
                if ret >= bl - 0.005:
                    dd["limit_up"] += 1
                elif ret <= -bl + 0.005:
                    dd["limit_down"] += 1
                if code in smallcap_codes:
                    dd["sc_rets"].append(ret)
            prev_close = c

    # 算 breadth + smallcap eq ret
    series: dict[str, dict] = {}
    for d in sorted(daily.keys()):
        dd = daily[d]
        total = dd["total"]
        breadth = dd["adv"] / total if total else 0
        sc_ret = sum(dd["sc_rets"]) / len(dd["sc_rets"]) if dd["sc_rets"] else 0
        series[d] = {
            "breadth": round(breadth, 4),
            "adv": dd["adv"], "dec": dd["dec"], "total": total,
            "limit_up": dd["limit_up"], "limit_down": dd["limit_down"],
            "smallcap_ret": round(sc_ret, 6),
        }
    return series


def save_breadth(series: dict) -> None:
    conn = sqlite3.connect(str(BREADTH_DB))
    conn.execute("""CREATE TABLE IF NOT EXISTS daily_breadth (
        date TEXT PRIMARY KEY, breadth REAL, adv INTEGER, dec INTEGER, total INTEGER,
        limit_up INTEGER, limit_down INTEGER, smallcap_ret REAL)""")
    rows = [(d, v["breadth"], v["adv"], v["dec"], v["total"], v["limit_up"], v["limit_down"], v["smallcap_ret"])
            for d, v in series.items()]
    conn.executemany("""INSERT OR REPLACE INTO daily_breadth
        (date, breadth, adv, dec, total, limit_up, limit_down, smallcap_ret)
        VALUES (?,?,?,?,?,?,?,?)""", rows)
    conn.commit()
    conn.close()


def load_breadth() -> dict[str, dict]:
    """读 daily_breadth 表 → {date: {breadth, adv, dec, total, limit_up, limit_down, smallcap_ret}}."""
    if not BREADTH_DB.exists():
        return {}
    conn = sqlite3.connect(str(BREADTH_DB))
    rows = conn.execute("""SELECT date, breadth, adv, dec, total, limit_up, limit_down, smallcap_ret
        FROM daily_breadth ORDER BY date""").fetchall()
    conn.close()
    return {d: {"breadth": b, "adv": a, "dec": de, "total": t, "limit_up": lu,
                "limit_down": ld, "smallcap_ret": sr}
            for d, b, a, de, t, lu, ld, sr in rows}


def backtest_capitulation(breadth_thresh: float, ld_thresh: int, hold: int, mode: str = "direct") -> None:
    """capitulation-bounce 回测：
    mode='direct'（诚实，无lookahead）: D 日 capitulation 确认 → D+1 买 → 持有 hold 天。
    mode='trigger'（有lookahead选择偏差，仅对照）: D+1..D+5 内 breadth>50%或sc_ret>0 才买（选择反弹成功的case=tautology）。
    - benchmark: 全期 random-day smallcap 买入持有 hold 天的平均
    - 非重叠 holding block（event edge 口径）
    """
    import statistics
    from math import erf, sqrt
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _factor_helpers import bonferroni_p, norm_sf_positive  # noqa: E402

    series = load_breadth()
    if not series:
        print("⚠️ 无 breadth 数据，先 --compute")
        return
    dates = sorted(series.keys())
    date_idx = {d: i for i, d in enumerate(dates)}
    sc_rets = [series[d]["smallcap_ret"] for d in dates]
    print(f"breadth series: {len(dates)} days ({dates[0]}~{dates[-1]}), mode={mode}")

    # 找 capitulation 日
    cap_days = [d for d in dates if series[d]["breadth"] < breadth_thresh or series[d]["limit_down"] > ld_thresh]
    print(f"capitulation 日（breadth<{breadth_thresh} 或 跌停>{ld_thresh}）: {len(cap_days)}")

    events: list[dict] = []
    last_exit_idx = -1
    for d in cap_days:
        di = date_idx[d]
        if mode == "direct":
            buy_idx = di + 1  # D+1 直接买，无 lookahead
        else:  # trigger (lookahead, 仅对照)
            trigger_offset = None
            for k in range(1, min(6, len(dates) - di)):
                td = dates[di + k]
                if series[td]["breadth"] > 0.50 or series[td]["smallcap_ret"] > 0:
                    trigger_offset = k
                    break
            if trigger_offset is None:
                continue
            buy_idx = di + trigger_offset
        exit_idx = buy_idx + hold
        if exit_idx >= len(dates):
            continue
        if buy_idx <= last_exit_idx:  # 非重叠
            continue
        fwd = 1.0
        for i in range(buy_idx, exit_idx):
            fwd *= (1 + sc_rets[i])
        fwd_ret = (fwd - 1) * 100
        events.append({"cap_date": d, "buy_date": dates[buy_idx], "exit_date": dates[exit_idx],
                       "fwd_ret": fwd_ret, "breadth_at_cap": series[d]["breadth"],
                       "ld_at_cap": series[d]["limit_down"]})
        last_exit_idx = exit_idx

    if len(events) < 10:
        print(f"⚠️ 事件数 {len(events)} < 10，underpowered")
        return

    rets = [e["fwd_ret"] for e in events]
    bench_rets: list[float] = []
    step = hold
    for i in range(0, len(dates) - hold, step):
        fwd = 1.0
        for j in range(i, i + hold):
            fwd *= (1 + sc_rets[j])
        bench_rets.append((fwd - 1) * 100)
    bench_mean = statistics.mean(bench_rets) if bench_rets else 0

    n = len(rets)
    mean = statistics.mean(rets)
    std = statistics.pstdev(rets) if n > 1 else 0
    se = std / sqrt(n) if n > 0 else 0
    t = mean / se if se > 0 else 0
    p = norm_sf_positive(t)
    wr = sum(1 for r in rets if r > 0) / n * 100
    excess = mean - bench_mean
    mid = n // 2
    train, test = rets[:mid], rets[mid:]

    print(f"\n{'='*70}\n=== capitulation-bounce 回测（mode={mode}, hold={hold}天，非重叠）===\n{'='*70}")
    print(f"事件数: {n}")
    print(f"  全期: mean={mean:.3f}% std={std:.3f}% WR={wr:.1f}% t={t:.2f} p_one_sided={p:.4f}")
    print(f"  benchmark(random-day hold={hold}): {bench_mean:.3f}% → excess={excess:.3f}%")
    if train and test:
        tr_m, te_m = statistics.mean(train), statistics.mean(test)
        tr_t = tr_m / (statistics.pstdev(train) / sqrt(len(train))) if len(train) > 1 and statistics.pstdev(train) > 0 else 0
        te_t = te_m / (statistics.pstdev(test) / sqrt(len(test))) if len(test) > 1 and statistics.pstdev(test) > 0 else 0
        te_p = norm_sf_positive(te_t)
        decay = (tr_m - te_m) / abs(tr_m) * 100 if tr_m != 0 else 0
        print(f"  walk-forward: train n={len(train)} mean={tr_m:.3f}% t={tr_t:.2f} | test n={len(test)} mean={te_m:.3f}% t={te_t:.2f} p={te_p:.4f}")
        print(f"  衰减: {decay:.0f}%")
    print(f"\n抽样事件（最近5）:")
    for e in events[-5:]:
        print(f"  {e['cap_date']}: breadth={e['breadth_at_cap']:.2%} 跌停={e['ld_at_cap']} → 买{e['buy_date']} 卖{e['exit_date']} ret={e['fwd_ret']:.2f}%")

    N_BONF = 4
    p_bonf = bonferroni_p(p, N_BONF)
    print(f"\n--- VERDICT（Bonf×{N_BONF}, event edge 口径）---")
    print(f"  excess={excess:.3f}% t={t:.2f} p={p} Bonf×{N_BONF}={p_bonf:.4f}")
    if excess < 0:
        print(f"  → FALSIFIED: excess {excess:.3f}% < 0")
    elif t < 2.9:
        print(f"  → KILL: excess>0 BUT t={t:.2f}<2.9")
    elif p_bonf >= 0.05:
        print(f"  → exploratory: Bonf {p_bonf:.4f}>=0.05")
    else:
        print(f"  → ✅ edge-confirmed-provisional（须幸存者+realizable 审查）")

    out = {"mode": mode, "n_events": n, "hold": hold, "mean": round(mean, 3),
           "excess": round(excess, 3), "t": round(t, 2), "p": p, "wr": round(wr, 1), "bonf_n": N_BONF}
    pth = Path(__file__).parent / f"_capitulation_bounce_{mode}_h{hold}_result.json"
    pth.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"result JSON -> {pth}")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--compute", action="store_true", help="算 breadth 时序")
    ap.add_argument("--backtest", action="store_true", help="跑 capitulation-bounce 回测")
    ap.add_argument("--breadth-thresh", type=float, default=0.05, help="breadth 阈值")
    ap.add_argument("--ld-thresh", type=int, default=50, help="跌停数阈值")
    ap.add_argument("--hold", type=int, default=5, help="持有天数")
    ap.add_argument("--mode", choices=["direct", "trigger"], default="direct", help="direct=D+1买无lookahead(诚实), trigger=反弹确认才买(有选择偏差,对照)")
    args = ap.parse_args()
    if args.compute:
        print("computing market breadth series (full market pass)...")
        series = compute_breadth_series()
        save_breadth(series)
        print(f"saved {len(series)} days to {BREADTH_DB}")
        cap_days = [(d, v) for d, v in series.items() if v["breadth"] < 0.05 or v["limit_down"] > 50]
        print(f"\ncapitulation 候选日（breadth<5% 或 跌停>50）: {len(cap_days)}")
        for d, v in sorted(cap_days)[-15:]:
            print(f"  {d}: breadth={v['breadth']:.2%} 跌停={v['limit_down']} 涨停={v['limit_up']} 小盘ret={v['smallcap_ret']:.4%}")
    elif args.backtest:
        backtest_capitulation(args.breadth_thresh, args.ld_thresh, args.hold, args.mode)
    else:
        print("用 --compute 算 breadth 时序，或 --backtest 跑回测")


if __name__ == "__main__":
    main()
