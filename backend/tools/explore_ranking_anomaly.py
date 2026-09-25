# -*- coding: utf-8 -*-
"""探索性：anomaly 异动股（rank_change 大）次日 T+1 edge + R4 filter 涨停股。

避开 V1 假 edge——R4 filter 涨停股后审剩余非涨停 edge。
- entry=次日 open + exit=次日 close 或 D+2 open（T+1）
- §44 v3 R4 compare_filtered_vs_unfiltered_edge（涨停 vs 未涨停对比）

数据：intraday_ranking_snapshots anomaly（14 天 <60 → exploratory）
跑法：cd backend && .venv/bin/python tools/explore_ranking_anomaly.py
"""
import json
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

INTRADAY = ROOT / ".vibe-research" / "intraday_accumulation" / "intraday_microstructure.db"
KLINE = ROOT / ".vibe-research" / "baostock_kline_cache.db"


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
    out = [{"date": str(b.get("date",""))[:10], "open": float(b.get("open",0) or 0),
            "close": float(b.get("close",0) or 0)}
           for b in bars if b.get("date") and float(b.get("open",0) or 0)>0]
    out.sort(key=lambda x: x["date"])
    return out


def main():
    db = sqlite3.connect(str(INTRADAY))
    # anomaly 异动 (date,code) + rank（最早 ts）——anomaly 无 rank_change，用 rank
    rows = db.execute("""
        SELECT date, code, rank FROM intraday_ranking_snapshots
        WHERE source='anomaly' AND rank IS NOT NULL
        ORDER BY date, code, ts
    """).fetchall()
    early = {}
    for date, code, rank in rows:
        if (date, code) not in early:
            early[(date, code)] = rank
    print(f"anomaly (date,code): {len(early)}", flush=True)

    obs = []
    cache = {}
    quote_cache = {}
    for (date, code), rank in early.items():
        if code not in cache:
            cache[code] = load_kline_bars(code)
        bars = cache[code]
        # 找 date bar + 次日 open
        idx = next((i for i, b in enumerate(bars) if b["date"] == date), None)
        if idx is None or idx + 2 >= len(bars):
            continue
        d1_open = bars[idx+1]["open"]
        d2_open = bars[idx+2]["open"]
        edge = (d2_open - d1_open) / d1_open
        # R4: 涨停股 filter（D 日涨停过？join quote price>=limit_up）
        if (date, code) not in quote_cache:
            q = db.execute("SELECT price, limit_up FROM intraday_quote_snapshots WHERE date=? AND code=? AND limit_up IS NOT NULL", (date, code)).fetchall()
            quote_cache[(date, code)] = any(p >= lu for p, lu in q if lu and lu > 0)
        is_zt = quote_cache[(date, code)]
        obs.append({"date": date, "code": code, "edge": edge, "win": 1 if edge > 0 else 0,
                    "rank": rank, "is_zt": is_zt})

    n = len(obs)
    days = len(set(o["date"] for o in obs))
    print(f"obs={n} days={days}")
    if n < 30:
        print(f"n={n}<30 → underpowered")
        return

    rets = [o["edge"] for o in obs]
    print(f"\n=== anomaly 异动 T+1 edge（全样本）===")
    print(f"n={n} days={days} net_mean={statistics.mean(rets)*100:.2f}% WR={sum(o['win'] for o in obs)/n*100:.2f}%")

    # 按 rank 分位（rank 小=异动大）
    groups = {"rank 1-10（异动大）": [o for o in obs if o["rank"]<=10],
              "rank 11-20": [o for o in obs if 10<o["rank"]<=20],
              "rank 21-30（异动小）": [o for o in obs if o["rank"]>20]}
    print(f"\n=== 按 rank 分组 ===")
    for name, g in groups.items():
        if not g: continue
        gr = [o["edge"] for o in g]
        print(f"  {name}: n={len(g)} net_mean={statistics.mean(gr)*100:.2f}% WR={sum(o['win'] for o in g)/len(g)*100:.2f}%")

    # §44 v3 R4: 涨停 vs 未涨停对比
    obs_zt = [o for o in obs if o["is_zt"]]
    obs_nonzt = [o for o in obs if not o["is_zt"]]
    print(f"\n=== R4 涨停 vs 未涨停（survivorship）===")
    if obs_zt:
        r = [o["edge"] for o in obs_zt]
        print(f"  涨停股: n={len(obs_zt)} net_mean={statistics.mean(r)*100:.2f}% WR={sum(o['win'] for o in obs_zt)/len(obs_zt)*100:.2f}%")
    if obs_nonzt:
        r = [o["edge"] for o in obs_nonzt]
        print(f"  未涨停股: n={len(obs_nonzt)} net_mean={statistics.mean(r)*100:.2f}% WR={sum(o['win'] for o in obs_nonzt)/len(obs_nonzt)*100:.2f}%")
        # R4 helper
        from s44_verifier.verifier import compare_filtered_vs_unfiltered_edge
        res = compare_filtered_vs_unfiltered_edge(obs, lambda o: o["is_zt"], dates=[o["date"] for o in obs])
        print(f"  R4 helper: filter_pct={res['filter_pct']}% contrib_pct={res['contrib_pct']}% is_fake_edge={res['is_fake_edge']} is_underpowered={res['is_underpowered']}")

    print(f"\n=== §44 v3 审 ===")
    print(f"  ✓ R4 filter 涨停股 survivorship 审")
    print(f"  ⚠ days={days}<60 → exploratory only")


if __name__ == "__main__":
    main()
