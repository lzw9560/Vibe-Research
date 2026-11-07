# -*- coding: utf-8 -*-
"""探索性：早盘 OFI（order flow imbalance）→ T+1 overnight edge。

信号：早盘 OFI 高（资金流入强）→ 次日 open 涨？
- entry=当日 open（市场价）——避开 V1 entry 涨停价
- exit=次日 open（T+1 制度）
- §44 v3 R1 entry 一字跌停 filter + R3 exit 次日一字 filter

数据：intraday_ofi_snapshots（8 天 <60 → exploratory only）
依赖：intraday_microstructure.db + baostock_kline_cache.db
跑法：cd backend && .venv/bin/python tools/explore_ofi_edge.py
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


def find_next_open(bars: list[dict], date: str) -> tuple[float, float, float, float] | None:
    """返 (prev_close, open, close, next_open)。prev_close=前一交易日 close（判 entry 一字涨停）。"""
    for i, b in enumerate(bars):
        if b["date"] == date:
            prev_c = bars[i - 1]["close"] if i > 0 else 0.0
            if i + 1 < len(bars):
                return (prev_c, b["open"], b["close"], bars[i + 1]["open"])
            return None
    return None


def main() -> dict:
    db = sqlite3.connect(str(INTRADAY))
    # 取早盘 OFI（最早 ts per code per date）
    rows = db.execute("""
        SELECT date, code, ofi, ofi_abs, bid_ask_pressure, seal_amount, ts
        FROM intraday_ofi_snapshots
        WHERE ofi IS NOT NULL
        ORDER BY date, code, ts
    """).fetchall()
    # per (date, code) 取最早 ts（早盘 OFI）
    early: dict[tuple, dict] = {}
    for date, code, ofi, ofi_abs, ba_press, seal, ts in rows:
        key = (date, code)
        if key not in early:
            early[key] = {"ofi": ofi, "ofi_abs": ofi_abs, "ba_press": ba_press, "seal": seal, "ts": ts}
    print(f"OFI snapshots: {len(rows)}, early (date,code): {len(early)}", flush=True)

    obs: list[dict] = []
    cache: dict[str, list] = {}
    for (date, code), info in early.items():
        if code not in cache:
            cache[code] = load_kline_bars(code)
        oc = find_next_open(cache[code], date)
        if not oc:
            continue
        prev_close, open_p, close_p, next_open = oc
        edge = (next_open - open_p) / open_p
        next_gap_pct = (next_open - close_p) / close_p * 100
        is_next_locked = abs(next_gap_pct) >= 9.5
        # §44 v3 R1 双向：entry 一字涨停（open vs prev_close 涨跌幅>=9.5% 买不到）
        # + 一字跌停（ofi<=0.05 全卖盘买不到）+ open=涨停价（prev_close>0 时）
        entry_open_pct = (open_p - prev_close) / prev_close * 100 if prev_close > 0 else 0
        is_entry_locked = (info["ofi"] or 0) <= 0.05 or entry_open_pct >= 9.5 or info["seal"] is not None
        obs.append(
            {
                "date": date,
                "code": code,
                "ofi": float(info["ofi"] or 0),
                "ofi_abs": float(info["ofi_abs"] or 0),
                "ba_press": float(info["ba_press"] or 0),
                "seal": info["seal"],
                "edge": edge,
                "win": 1 if edge > 0 else 0,
                "next_locked": is_next_locked,
                "entry_locked": is_entry_locked,
            }
        )
    n = len(obs)
    days = len(set(o["date"] for o in obs))
    print(f"obs={n} days={days} (join kline 后)", flush=True)
    if n < 30:
        print(f"n={n}<30 → underpowered")
        return {"status": "underpowered", "n": n, "days": days}

    rets = [o["edge"] for o in obs]
    wr = sum(o["win"] for o in obs) / n
    net_mean = statistics.mean(rets)
    print(f"\n=== 全样本 T+1 edge（early OFI）===")
    print(f"n={n} days={days} net_mean={net_mean * 100:.2f}% WR={wr * 100:.2f}%")

    # 分组 by OFI 分位（深挖不同阈值稳健性）
    buckets = {"OFI 0.7-0.8": [], "OFI 0.8-0.9": [], "OFI 0.9-0.95": [], "OFI>=0.95": []}
    for o in obs:
        ofi = o["ofi"]
        if 0.7 <= ofi < 0.8:
            buckets["OFI 0.7-0.8"].append(o)
        elif 0.8 <= ofi < 0.9:
            buckets["OFI 0.8-0.9"].append(o)
        elif 0.9 <= ofi < 0.95:
            buckets["OFI 0.9-0.95"].append(o)
        elif ofi >= 0.95:
            buckets["OFI>=0.95"].append(o)
    print(f"\n=== 按 early OFI 细分组 T+1 edge（稳健性）===")
    for name in ["OFI 0.7-0.8", "OFI 0.8-0.9", "OFI 0.9-0.95", "OFI>=0.95"]:
        group = buckets.get(name, [])
        if not group:
            print(f"  {name}: n=0")
            continue
        g_rets = [o["edge"] for o in group]
        g_wr = sum(o["win"] for o in group) / len(group)
        g_mean = statistics.mean(g_rets)
        g_days = len(set(o["date"] for o in group))
        print(f"  {name}: n={len(group)} days={g_days} net_mean={g_mean * 100:.2f}% WR={g_wr * 100:.2f}%")

    # §44 v3 R1+R3 filter
    obs_r1 = [o for o in obs if not o["entry_locked"]]
    obs_f = [o for o in obs_r1 if not o["next_locked"]]
    print(f"\n=== §44 v3 R1+R3 filter ===")
    print(f"  R1 entry filter（ofi>0.05 + open 非一字涨停）: {n}→{len(obs_r1)}")
    print(f"  R3 exit filter（次日非一字）: {len(obs_r1)}→{len(obs_f)}")
    # filter 后高 OFI edge（验证是否涨停封板溢价 over-credit）
    high_f = [o for o in obs_f if o["ofi"] >= 0.7]
    if high_f:
        hf_rets = [o["edge"] for o in high_f]
        print(
            f"  filter 后 高OFI(>=0.7): n={len(high_f)} net_mean={statistics.mean(hf_rets) * 100:.2f}% WR={sum(o['win'] for o in high_f) / len(high_f) * 100:.2f}%"
        )
        print(f"  （vs filter 前 高OFI +6.24% WR 78%——若衰减多则涨停封板溢价 over-credit）")

    try:
        from s44_verifier.stats import day_clustered_t_test

        dts = [o["date"] for o in obs_f]
        rets_f = [o["edge"] for o in obs_f]
        res = day_clustered_t_test(rets_f, dts)
        print(f"\n=== §44 day_clustered t-test（filter 后）===")
        print(f"  t={res.t_stat:.3f} p_one_sided={res.p_one_sided:.4f}")
        print(f"  days={days}<60 → exploratory only")
    except Exception as e:
        print(f"§44 stats err: {e}")

    print(f"\n=== §44 v3 审 ===")
    print(f"  ✓ entry=open 市场价（非涨停价）")
    print(f"  ✓ exit=次日 open T+1 + R3 filter 次日一字")
    print(f"  ⚠ days={days}<60 → exploratory only")
    return {"n": n, "days": days, "net_mean_pct": round(net_mean * 100, 4)}


if __name__ == "__main__":
    main()
