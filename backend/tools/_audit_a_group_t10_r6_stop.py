# -*- coding: utf-8 -*-
"""A组 T+10 R6 intraday stop（#3 8步 ⑦，lottery 结构 stop 验证）。

_a_group_t10_walkforward.py: T+10 walk-forward OOS edge-confirmed（train+0.912%/test+1.094% PASS）。
但 lottery 结构（median 负/零 WR<50%），靠尾部大涨拉均值。
R6: T+2 open 买，T+2~T+10 任何日 low <= -3% stop_price 则止损 -3%，否则 hold 到 T+10 close。
看 stop 是否压低 mean 但提高 WR（lottery cutoff）。
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
STOP_PCT = -3.0
ALPHA = 0.05


def load_a_group_picks() -> list:
    conn = sqlite3.connect(str(DT_DB))
    rows = conn.execute("""
        SELECT trade_date, security_code, SUM(net) as total_net, MAX(change_rate) as chg
        FROM dragon_tiger_rows
        WHERE side='buy' AND net IS NOT NULL
        GROUP BY trade_date, security_code
    """).fetchall()
    conn.close()
    picks = []
    for date, code, total_net, chg in rows:
        if total_net is None or chg is None:
            continue
        if not (-3 <= chg <= 10):
            continue
        if total_net <= 0:
            continue
        if total_net > 5e7:
            continue
        picks.append((date, code))
    return sorted(picks)


def load_kline(code: str) -> list:
    conn = sqlite3.connect(str(KLINE_DB))
    row = conn.execute("SELECT bars_json FROM kline WHERE code=?", (code,)).fetchone()
    conn.close()
    if not row:
        return []
    try:
        return sorted(json.loads(row[0]), key=lambda b: b.get("date", ""))
    except Exception:
        return []


_KLINE_CACHE: dict = {}


def compute_t10_with_stop(code: str, trade_date: str) -> tuple:
    """T+2 open 买，T+2~T+9 任何日 close 跌破-3% 触发→次日 open 成交（gap-through），否则 hold T+10 close。

    诚实口径修正（2026-10-07，工程底线 #1，同 inst_dominant）：
    原逻辑 T+2~T+10 任何日 low <= stop_price 按 stop_price(-3%) stop——
    T+2 当天买入 low 触及不能卖（A 股 T+1）；且 low 触及按 stop_price 精确成交不现实（跳空穿仓应按 open）。
    改为 close 触发（等收盘确认）+ 次日 open 成交（gap-through：跳空按 open 更差，反弹也按 open）。

    返回 (return%, status)。status: stop_next_open / hold / None。
    """
    if code not in _KLINE_CACHE:
        _KLINE_CACHE[code] = load_kline(code)
    bars = _KLINE_CACHE[code]
    after = [b for b in bars if b.get("date", "") > trade_date]
    if len(after) < 10:  # T+1~T+10 = after[0]~after[9]
        return None, None
    t2 = after[1]  # T+2 open 买
    t2_open = t2.get("open")
    if not t2_open or t2_open <= 0:
        return None, None
    stop_price = t2_open * (1 + STOP_PCT / 100)
    # check T+2~T+9 daily close 触发（after[1]~after[8]），触发→次日 open 成交
    for i in range(1, 9):  # T+2~T+9
        if i + 1 >= len(after):
            return None, None
        day_close = after[i].get("close")
        if day_close is not None and day_close <= stop_price:
            # 次日 open 成交（gap-through）
            next_open = after[i + 1].get("open")
            if not next_open or next_open <= 0:
                return None, None
            return (next_open / t2_open - 1) * 100, "stop_next_open"
    t10_close = after[9].get("close")  # T+10 close
    if not t10_close:
        return None, None
    return (t10_close / t2_open - 1) * 100, "hold"


def normal_p(t: float) -> float:
    return 2 * (1 - 0.5 * (1 + erf(abs(t) / (2 ** 0.5))))


def stats(rbd: dict, ar: list) -> dict:
    day_means = [statistics.mean(rs) for rs in rbd.values() if rs]
    if len(day_means) < 2:
        return {}
    mean = statistics.mean(day_means)
    n_days = len(day_means)
    se = statistics.stdev(day_means) / (n_days ** 0.5) if n_days > 1 else 0
    t = mean / se if se > 0 else 0
    n = len(ar)
    wr = sum(1 for r in ar if r > 0) / n * 100 if n else 0
    sr = sorted(ar)
    median = sr[n // 2] if n else 0
    return {"n": n, "days": n_days, "mean": mean, "median": median, "wr": wr, "t": t, "p": normal_p(t)}


def audit_r6() -> None:
    picks = load_a_group_picks()
    print(f"=== A组 T+10 R6 intraday stop（#3 8步 ⑦）===")
    print(f"A组 picks: {len(picks)}\n")

    rbd: dict = defaultdict(list)
    ar: list = []
    stopped = 0
    for date, code in picks:
        r, status = compute_t10_with_stop(code, date)
        if r is not None:
            rbd[date].append(r)
            ar.append(r)
            if status == "stop_next_open":
                stopped += 1

    s = stats(rbd, ar)
    if not s:
        print("无数据")
        return
    stop_rate = stopped / s["n"] * 100 if s["n"] else 0
    print(f"  T+10 with -3% intraday stop:")
    print(f"  n={s['n']} days={s['days']} mean={s['mean']:.3f}% median={s['median']:.3f}% "
          f"WR={s['wr']:.1f}% day_t={s['t']:.2f} p={s['p']:.4f}")
    print(f"  stop_rate: {stop_rate:.1f}% ({stopped}/{s['n']})")
    print(f"  Bonf×4={min(1.0, s['p'] * 4):.4f}")
    print(f"\n  对比 no-stop T+10 (walkforward 全量): mean+0.989% median-0.095% WR49.1%")
    print(f"  → stop {'压低 mean' if s['mean'] < 0.989 else '未压低 mean'} + {'提高 WR' if s['wr'] > 49.1 else '未提高 WR'}")
    if s["p"] < ALPHA and s["mean"] > 0:
        print(f"  → R6 PASS: T+10 with stop edge-confirmed（lottery cutoff 后仍正显著）")
    else:
        print(f"  → R6 FAIL: stop 压掉 edge（lottery 靠尾部，stop 切尾部 → mean 转负/不显著）")


if __name__ == "__main__":
    audit_r6()
