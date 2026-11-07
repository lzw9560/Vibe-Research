# -*- coding: utf-8 -*-
"""探索性：封板时机（秒板 vs 尾盘封板）→ T+1 overnight edge。

信号：最早封板 ts（<10:00 秒板 momentum 强 vs 14+ 尾盘封板弱）
- entry=当日 open（市场价）——避开 V1 entry 涨停价（R1 filter 一字涨停）
- exit=次日 open（T+1）+ R3 filter 次日一字
- §44 v3 审

数据：intraday_quote_snapshots（14 天 <60 → exploratory）
跑法：cd backend && .venv/bin/python tools/explore_seal_timing_edge.py
"""

import json
import sqlite3
import statistics
import sys
from pathlib import Path

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

INTRADAY = resolve_data_dir() / "intraday_accumulation" / "intraday_microstructure.db"
KLINE = resolve_data_dir() / "baostock_kline_cache.db"


def load_kline_bars(code: str) -> list[dict]:
    db = sqlite3.connect(str(KLINE))
    row = db.execute("SELECT bars_json FROM kline WHERE code=?", (code,)).fetchone()
    db.close()
    if not row or not row[0]:
        return []
    try:
        bars = json.loads(row[0])
    except Exception:
        return []
    out = [
        {
            "date": str(b.get("date", ""))[:10],
            "open": float(b.get("open", 0) or 0),
            "close": float(b.get("close", 0) or 0),
        }
        for b in bars
        if b.get("date") and float(b.get("open", 0) or 0) > 0
    ]
    out.sort(key=lambda x: x["date"])
    return out


def find_next_open(bars, date):
    for i, b in enumerate(bars):
        if b["date"] == date:
            prev_c = bars[i - 1]["close"] if i > 0 else 0.0
            if i + 1 < len(bars):
                return (prev_c, b["open"], b["close"], bars[i + 1]["open"])
            return None
    return None


def main():
    db = sqlite3.connect(str(INTRADAY))
    # per (date,code) 最早封板 ts（price>=limit_up）
    rows = db.execute("""
        SELECT date, code, ts FROM intraday_quote_snapshots
        WHERE limit_up IS NOT NULL AND price>=limit_up
        ORDER BY date, code, ts
    """).fetchall()
    early = {}
    for date, code, ts in rows:
        if (date, code) not in early:
            early[(date, code)] = ts
    print(f"涨停 (date,code): {len(early)}", flush=True)

    obs = []
    cache = {}
    for (date, code), ts in early.items():
        if code not in cache:
            cache[code] = load_kline_bars(code)
        oc = find_next_open(cache[code], date)
        if not oc:
            continue
        prev_close, open_p, close_p, next_open = oc
        edge = (next_open - open_p) / open_p
        hh = ts.split("T")[1][:2] if "T" in ts else "00"
        try:
            h = int(hh)
        except ValueError:
            h = 0
        # 封板时机分桶
        if h < 10:
            bucket = "秒板(<10:00)"
        elif h < 11:
            bucket = "早盘(10-11)"
        elif h < 14:
            bucket = "盘中(11-14)"
        else:
            bucket = "尾盘(14+)"
        next_gap_pct = (next_open - close_p) / close_p * 100
        is_next_locked = abs(next_gap_pct) >= 9.5
        entry_open_pct = (open_p - prev_close) / prev_close * 100 if prev_close > 0 else 0
        # R1 entry 一字涨停（open=涨停价买不到）+ 一字跌停（open vs prev_close<=-9.5%）
        is_entry_locked = entry_open_pct >= 9.5 or entry_open_pct <= -9.5
        obs.append(
            {
                "date": date,
                "code": code,
                "bucket": bucket,
                "edge": edge,
                "win": 1 if edge > 0 else 0,
                "next_locked": is_next_locked,
                "entry_locked": is_entry_locked,
            }
        )

    n = len(obs)
    days = len(set(o["date"] for o in obs))
    print(f"obs={n} days={days}")
    if n < 30:
        print(f"n={n}<30 → underpowered")
        return

    # 按 bucket 分组
    print(f"\n=== 按封板时机分组 T+1 edge（全样本）===")
    from collections import defaultdict

    groups = defaultdict(list)
    for o in obs:
        groups[o["bucket"]].append(o)
    for name in ["秒板(<10:00)", "早盘(10-11)", "盘中(11-14)", "尾盘(14+)"]:
        g = groups.get(name, [])
        if not g:
            continue
        g_rets = [o["edge"] for o in g]
        g_wr = sum(o["win"] for o in g) / len(g)
        print(
            f"  {name}: n={len(g)} days={len(set(o['date'] for o in g))} net_mean={statistics.mean(g_rets) * 100:.2f}% WR={g_wr * 100:.2f}%"
        )

    # §44 v3 R1+R3 filter
    obs_f = [o for o in obs if not o["entry_locked"] and not o["next_locked"]]
    print(f"\n=== §44 v3 R1+R3 filter ===")
    print(f"  filter: {n}→{len(obs_f)}")
    print(f"\n=== filter 后按封板时机分组 ===")
    groups_f = defaultdict(list)
    for o in obs_f:
        groups_f[o["bucket"]].append(o)
    for name in ["秒板(<10:00)", "早盘(10-11)", "盘中(11-14)", "尾盘(14+)"]:
        g = groups_f.get(name, [])
        if not g:
            continue
        g_rets = [o["edge"] for o in g]
        g_wr = sum(o["win"] for o in g) / len(g)
        print(f"  {name}: n={len(g)} net_mean={statistics.mean(g_rets) * 100:.2f}% WR={g_wr * 100:.2f}%")

    try:
        from s44_verifier.stats import day_clustered_t_test

        dts = [o["date"] for o in obs_f]
        rets_f = [o["edge"] for o in obs_f]
        res = day_clustered_t_test(rets_f, dts)
        print(f"\n=== §44 t-test（filter 后全样本）===")
        print(f"  t={res.t_stat:.3f} p_one_sided={res.p_one_sided:.4f} (days={days}<60 exploratory)")
    except Exception as e:
        print(f"§44 stats err: {e}")


if __name__ == "__main__":
    main()
