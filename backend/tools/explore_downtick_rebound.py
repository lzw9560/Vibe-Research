# -*- coding: utf-8 -*-
"""探索性：跌停股次日反弹 edge（D 跌停→次日 open 反弹，非涨停 survivorship）。

避开 V1 假 edge 覆辙（涨停封板溢价 + survivorship）——跌停股是逆向，非涨停 momentum。
- entry=次日 open（市场价，D+1 跌停股次日开盘买）
- exit=次日 close 或 D+2 open（T+1 制度，当日买次日卖）
- §44 v3 R1 entry 一字跌停 filter（D+1 open=跌停价买不到）+ R3 exit 一字 filter

数据：intraday_quote_snapshots（14 天 <60 → exploratory）
跑法：cd backend && .venv/bin/python tools/explore_downtick_rebound.py
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


def load_kline_bars(code):
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
            if i + 2 < len(bars):
                # D 跌停，entry=D+1 open（次日买），exit=D+2 open（T+1 卖）
                return (prev_c, b["open"], b["close"], bars[i + 1]["open"], bars[i + 1]["close"], bars[i + 2]["open"])
            return None
    return None


def main():
    db = sqlite3.connect(str(INTRADAY))
    # D 日跌停股（price<=limit_down，最早 ts 跌停）
    rows = db.execute("""
        SELECT date, code, ts FROM intraday_quote_snapshots
        WHERE limit_down IS NOT NULL AND price<=limit_down
        ORDER BY date, code, ts
    """).fetchall()
    early = {}
    for date, code, ts in rows:
        if (date, code) not in early:
            early[(date, code)] = ts
    print(f"跌停 (date,code): {len(early)}", flush=True)

    obs = []
    cache = {}
    for (date, code), ts in early.items():
        if code not in cache:
            cache[code] = load_kline_bars(code)
        oc = find_next_open(cache[code], date)
        if not oc:
            continue
        prev_close, d_open, d_close, d1_open, d1_close, d2_open = oc
        # entry=D+1 open（次日开盘买），exit=D+2 open（T+1 次日开盘卖）
        edge = (d2_open - d1_open) / d1_open
        # R1 entry 一字跌停（D+1 open=跌停价买不到）：d1_open vs d_close 涨跌幅<=-9.5%
        d1_open_pct = (d1_open - d_close) / d_close * 100 if d_close > 0 else 0
        is_entry_locked = d1_open_pct <= -9.5
        # R3 exit 一字（D+2 open vs d1_close 涨跌幅 abs>=9.5%）
        d2_gap_pct = (d2_open - d1_close) / d1_close * 100 if d1_close > 0 else 0
        is_exit_locked = abs(d2_gap_pct) >= 9.5
        obs.append(
            {
                "date": date,
                "code": code,
                "edge": edge,
                "win": 1 if edge > 0 else 0,
                "entry_locked": is_entry_locked,
                "exit_locked": is_exit_locked,
            }
        )

    n = len(obs)
    days = len(set(o["date"] for o in obs))
    print(f"obs={n} days={days}")
    if n < 30:
        print(f"n={n}<30 → underpowered")
        return

    rets = [o["edge"] for o in obs]
    wr = sum(o["win"] for o in obs) / n
    print(f"\n=== 跌停股次日反弹 T+1 edge（全样本）===")
    print(f"n={n} days={days} net_mean={statistics.mean(rets) * 100:.2f}% WR={wr * 100:.2f}%")

    # §44 v3 R1+R3 filter
    obs_f = [o for o in obs if not o["entry_locked"] and not o["exit_locked"]]
    print(f"\n=== R1+R3 filter 后 ===")
    print(f"  filter: {n}→{len(obs_f)}")
    if obs_f:
        rets_f = [o["edge"] for o in obs_f]
        wr_f = sum(o["win"] for o in obs_f) / len(obs_f)
        print(f"  n={len(obs_f)} net_mean={statistics.mean(rets_f) * 100:.2f}% WR={wr_f * 100:.2f}%")
        try:
            from s44_verifier.stats import day_clustered_t_test

            dts = [o["date"] for o in obs_f]
            res = day_clustered_t_test(rets_f, dts)
            print(f"  §44 t={res.t_stat:.3f} p_one_sided={res.p_one_sided:.4f} (days={days}<60 exploratory)")
        except Exception as e:
            print(f"  §44 stats err: {e}")

    print(f"\n=== §44 v3 审 ===")
    print(f"  ✓ 跌停股=逆向非涨停 survivorship（避开 V1 假 edge）")
    print(f"  ✓ entry=D+1 open 市场价 + R1 filter 一字跌停")
    print(f"  ✓ exit=D+2 open T+1 + R3 filter 一字")
    print(f"  ⚠ days={days}<60 → exploratory only")


if __name__ == "__main__":
    main()
