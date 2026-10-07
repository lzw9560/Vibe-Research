# -*- coding: utf-8 -*-
"""LHB inst_dominant 全量验证 + 跨 regime 分层 + intraday gap-through stop。

_inst_stop.py 采样 5000 + 简化 stop（T+1 close 跌破）。
本脚本：全量不采样 + 跨 regime 分层（2018-2024 vs 2025-2026）+ intraday gap-through stop
（T+1 low 跌破 -3% 按 stop 价成交，R6 realistic fill）。

确认 inst_dominant 是否真 edge-confirmed（项目首个 buy-side edge 候选）。
"""
import json
import sqlite3
import statistics
from pathlib import Path
from collections import defaultdict
from math import erf

DATA = Path(__file__).resolve().parents[2] / ".vibe-research"
DT_DB = DATA / "dragon_tiger_history.db"
KLINE_DB = DATA / "baostock_kline_cache.db"

INST_KEYWORDS = (
    "机构专用", "总部", "高盛", "瑞银", "股通", "摩根",
    "中信证券股份有限公司上海分公司", "国际金融",
)
STOP_PCT = -3.0
ALPHA = 0.05


def load_picks_by_layer() -> dict:
    conn = sqlite3.connect(str(DT_DB))
    rows = conn.execute(
        "SELECT trade_date, security_code, dept_name, buy, net "
        "FROM dragon_tiger_rows WHERE side='buy' AND buy > 0"
    ).fetchall()
    conn.close()
    picks: dict = defaultdict(list)
    for date, code, dept, buy, net in rows:
        picks[(date, code)].append((dept or "", buy or 0, net or 0))
    layers: dict = {"inst_dominant": [], "lhb_mixed": [], "inst_selling": []}
    for (date, code), seats in picks.items():
        total_buy = sum(s[1] for s in seats)
        if total_buy <= 0:
            continue
        inst_buy = sum(s[1] for s in seats if any(k in s[0] for k in INST_KEYWORDS))
        inst_net_pct = inst_buy / total_buy
        net_total = sum(s[2] for s in seats)
        if inst_net_pct > 0.5:
            layers["inst_dominant"].append((date, code))
        elif net_total < 0:
            layers["inst_selling"].append((date, code))
        else:
            layers["lhb_mixed"].append((date, code))
    return layers


def load_kline(code: str) -> list:
    conn = sqlite3.connect(str(KLINE_DB))
    row = conn.execute("SELECT bars_json FROM kline WHERE code=?", (code,)).fetchone()
    conn.close()
    if not row:
        return []
    try:
        bars = json.loads(row[0])
        return sorted(bars, key=lambda b: b.get("date", ""))
    except Exception:
        return []


def compute_stop_intraday(code: str, trade_date: str, kline_cache: dict) -> tuple:
    """intraday gap-through stop: T+1 open 买入, T+1 low 跌破 -3% 按 stop 价成交, 否则 T+2 close 卖。"""
    if code not in kline_cache:
        kline_cache[code] = load_kline(code)
    bars = kline_cache[code]
    after = [b for b in bars if b.get("date", "") > trade_date]
    if len(after) < 2:
        return None, None
    t1 = after[0]
    t2 = after[1]
    t1_open = t1.get("open")
    t1_low = t1.get("low")
    t2_close = t2.get("close")
    if not t1_open or t1_open <= 0:
        return None, None
    stop_price = t1_open * (1 + STOP_PCT / 100)  # -3% = 0.97 * open
    # intraday gap-through: T+1 low 跌破 stop 价 → 按 stop 价成交（R6 realistic fill）
    if t1_low is not None and t1_low <= stop_price:
        return (stop_price / t1_open - 1) * 100, "stop_intraday"
    # 否则 T+2 close 卖
    if not t2_close:
        return None, None
    return (t2_close / t1_open - 1) * 100, "hold"


def normal_p(t: float) -> float:
    return 2 * (1 - 0.5 * (1 + erf(abs(t) / (2 ** 0.5))))


def stats_for(returns_by_date: dict, all_returns: list, stop_count: int) -> dict:
    day_means = [statistics.mean(rs) for rs in returns_by_date.values() if rs]
    if len(day_means) < 2:
        return {}
    mean = statistics.mean(day_means)
    n_days = len(day_means)
    se = statistics.stdev(day_means) / (n_days ** 0.5) if n_days > 1 else 0
    t = mean / se if se > 0 else 0
    n_picks = len(all_returns)
    wr = sum(1 for r in all_returns if r > 0) / n_picks * 100 if n_picks else 0
    sorted_r = sorted(all_returns)
    median = sorted_r[n_picks // 2] if n_picks else 0
    stop_rate = stop_count / n_picks * 100 if n_picks else 0
    p = normal_p(t)
    return {
        "n_picks": n_picks, "n_days": n_days, "mean": mean, "median": median,
        "wr": wr, "stop_rate": stop_rate, "t": t, "p": p,
    }


def audit_full() -> None:
    layers = load_picks_by_layer()
    kline_cache: dict = {}

    print(f"=== LHB inst_dominant 全量 + intraday gap-through stop ===\n")

    for layer_name, picks in layers.items():
        # 全量不采样
        returns_by_date: dict = defaultdict(list)
        all_returns: list = []
        stop_count = 0
        # 跨 regime 分层
        by_regime: dict = {"2018-2024": defaultdict(list), "2025-2026": defaultdict(list)}
        by_regime_returns: dict = {"2018-2024": [], "2025-2026": []}
        by_regime_stop: dict = {"2018-2024": 0, "2025-2026": 0}

        for date, code in picks:
            r, status = compute_stop_intraday(code, date, kline_cache)
            if r is not None:
                returns_by_date[date].append(r)
                all_returns.append(r)
                if status == "stop_intraday":
                    stop_count += 1
                regime = "2025-2026" if date >= "2025" else "2018-2024"
                by_regime[regime][date].append(r)
                by_regime_returns[regime].append(r)
                if status == "stop_intraday":
                    by_regime_stop[regime] += 1

        s = stats_for(returns_by_date, all_returns, stop_count)
        if not s:
            print(f"  {layer_name}: 数据不足")
            continue
        p_bonf = min(1.0, s["p"] * 3)
        verdict = "PASS" if p_bonf < ALPHA else "FAIL"
        print(f"  [{layer_name}] 全量: n={s['n_picks']} days={s['n_days']} "
              f"mean={s['mean']:.3f}% median={s['median']:.3f}% WR={s['wr']:.1f}% "
              f"stop_rate={s['stop_rate']:.1f}% day_t={s['t']:.2f} "
              f"p={s['p']:.4f} Bonf×3={p_bonf:.4f} {verdict}")

        # 跨 regime 分层
        for regime, rbd in by_regime.items():
            ar = by_regime_returns[regime]
            sc = by_regime_stop[regime]
            if not ar:
                continue
            sr = stats_for(rbd, ar, sc)
            if sr:
                pr = min(1.0, sr["p"] * 3)
                v = "PASS" if pr < ALPHA else "FAIL"
                print(f"    {regime}: n={sr['n_picks']} days={sr['n_days']} "
                      f"mean={sr['mean']:.3f}% median={sr['median']:.3f}% "
                      f"WR={sr['wr']:.1f}% stop={sr['stop_rate']:.1f}% "
                      f"t={sr['t']:.2f} p={sr['p']:.4f} Bonf×3={pr:.4f} {v}")
        print()


if __name__ == "__main__":
    audit_full()
