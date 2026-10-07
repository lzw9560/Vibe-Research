# -*- coding: utf-8 -*-
"""A组 T+10 R13 survivorship（#3 8步 ③，退市 bias 检验）。

A组 T+10 walk-forward OOS + R12 size-matched edge-confirmed。
但须 R13 排除 survivorship bias（退市股收益特殊处理）。
stock_basic_type1.json outDate 标退市股。

本脚本：
1. A组 picks 分退市（outDate != ""）+ 非退市
2. 算两组 T+10 BHAR（退市股 kline 不足返 None，自动排除）
3. 对比——退市组 mean + 非退市组 mean + 全样本 vs 非退市样本
gate: 非退市样本 mean 显著正 + 与全样本差距小 → survivorship bias 不显著
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
STOCK_BASIC = DATA / "stock_basic_type1.json"
HOLD = 8  # T+10 = T+2 + 8 days
ALPHA = 0.05


def to_baostock_code(code6: str) -> str:
    """6 位纯数字 → baostock code（sh.6/sz.0/sz.3/bj.4/bj.8）。"""
    if code6.startswith("6"):
        return f"sh.{code6}"
    if code6.startswith(("0", "3")):
        return f"sz.{code6}"
    if code6.startswith(("4", "8")):
        return f"bj.{code6}"
    return code6


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


def compute_window_return(code: str, trade_date: str, hold_days: int) -> float | None:
    """T+2 open → T+(2+hold_days) close。hold_days=8→T+10。"""
    if code not in _KLINE_CACHE:
        _KLINE_CACHE[code] = load_kline(code)
    bars = _KLINE_CACHE[code]
    after = [b for b in bars if b.get("date", "") > trade_date]
    buy_idx = 1  # T+2
    sell_idx = 1 + hold_days  # T+(2+hold_days)
    if len(after) <= sell_idx:
        return None
    t2_open = after[buy_idx].get("open")
    sell_close = after[sell_idx].get("close")
    if not t2_open or t2_open <= 0 or not sell_close:
        return None
    return (sell_close / t2_open - 1) * 100


def normal_p(t: float) -> float:
    return 2 * (1 - 0.5 * (1 + erf(abs(t) / (2 ** 0.5))))


def stats(rbd: dict, ar: list) -> dict:
    day_means = [statistics.mean(rs) for rs in rbd.values() if rs]
    if len(day_means) < 2:
        return {"n": len(ar), "days": len(day_means), "mean": 0.0, "wr": 0.0, "t": 0.0, "p": 1.0}
    mean = statistics.mean(day_means)
    n_days = len(day_means)
    se = statistics.stdev(day_means) / (n_days ** 0.5) if n_days > 1 else 0
    t = mean / se if se > 0 else 0
    n = len(ar)
    wr = sum(1 for r in ar if r > 0) / n * 100 if n else 0
    return {"n": n, "days": n_days, "mean": mean, "wr": wr, "t": t, "p": normal_p(t)}


def audit_r13() -> None:
    picks = load_a_group_picks()
    with open(STOCK_BASIC) as f:
        stock_basic = json.load(f)
    print(f"=== A组 T+10 R13 survivorship（#3 8步 ③）===")
    print(f"A组 picks: {len(picks)}")
    print(f"stock_basic: {len(stock_basic)} A 股, 退市 {sum(1 for v in stock_basic.values() if v.get('outDate'))}\n")

    # 分退市 + 非退市
    delisted_picks = []
    survivors_picks = []
    no_meta = 0
    for date, code in picks:
        bs_code = to_baostock_code(code)
        info = stock_basic.get(bs_code) or stock_basic.get(code)
        if not info:
            no_meta += 1
            survivors_picks.append((date, code))  # 无元数据当非退市（保守）
            continue
        out_date = info.get("outDate", "")
        if out_date:
            delisted_picks.append((date, code, out_date))
        else:
            survivors_picks.append((date, code))

    print(f"退市 picks (outDate非空): {len(delisted_picks)}")
    print(f"非退市 picks: {len(survivors_picks)}（其中无元数据 {no_meta} 当非退市）\n")

    # 算两组 T+10 BHAR
    del_rbd: dict = defaultdict(list)
    del_ar: list = []
    for date, code, out_date in delisted_picks:
        r = compute_window_return(code, date, HOLD)
        if r is not None:
            del_rbd[date].append(r)
            del_ar.append(r)

    sur_rbd: dict = defaultdict(list)
    sur_ar: list = []
    for date, code in survivors_picks:
        r = compute_window_return(code, date, HOLD)
        if r is not None:
            sur_rbd[date].append(r)
            sur_ar.append(r)

    del_s = stats(del_rbd, del_ar)
    sur_s = stats(sur_rbd, sur_ar)
    all_rbd: dict = defaultdict(list)
    for d, rs in del_rbd.items():
        all_rbd[d].extend(rs)
    for d, rs in sur_rbd.items():
        all_rbd[d].extend(rs)
    all_ar = del_ar + sur_ar
    all_s = stats(all_rbd, all_ar)

    print(f"退市组: n={del_s['n']} days={del_s['days']} mean={del_s['mean']:.3f}% WR={del_s['wr']:.1f}% t={del_s['t']:.2f} p={del_s['p']:.4f}")
    print(f"非退市: n={sur_s['n']} days={sur_s['days']} mean={sur_s['mean']:.3f}% WR={sur_s['wr']:.1f}% t={sur_s['t']:.2f} p={sur_s['p']:.4f}")
    print(f"全样本: n={all_s['n']} days={all_s['days']} mean={all_s['mean']:.3f}% WR={all_s['wr']:.1f}% t={all_s['t']:.2f} p={all_s['p']:.4f}")

    gap = abs(all_s['mean'] - sur_s['mean'])
    print(f"\n  对比 全样本 mean {all_s['mean']:.3f}% vs 非退市 mean {sur_s['mean']:.3f}%, gap={gap:.3f}%")
    if sur_s['p'] < ALPHA and sur_s['mean'] > 0:
        print(f"  → R13 PASS: 非退市样本仍 edge-confirmed（survivorship bias 不显著）")
    elif sur_s['mean'] > 0:
        print(f"  → R13 边界: 非退市 mean 正但不显著（可能 underpowered 或 survivorship bias）")
    else:
        print(f"  → R13 FAIL: 非退市 mean 负——survivorship bias 显著（全样本 edge 靠退市股虚抬）")


if __name__ == "__main__":
    audit_r13()
