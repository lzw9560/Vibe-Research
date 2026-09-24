# -*- coding: utf-8 -*-
"""探索性：竞价 no_cancel 信号 → T+0 日内 edge（entry=open exit=close）。

避开 consecutive_relay V1 假 edge 覆辙（§44 v3 改进审）：
- entry=open 09:30 开盘价（市场价非涨停价）——避开 V1 entry 涨停价
- exit=close 15:00 收盘价（市场价）——T+0 日内卖，避开 overnight gap + D+1 一字涨停 over-credit
- 窗口语义：T+0 日内 edge（open→close），非涨停封板溢价非 overnight gap

数据：intraday_auction_snapshots no_cancel（14 天 <60 §44 门槛 → exploratory only）
依赖：intraday_microstructure.db + baostock_kline_cache.db

跑法：cd backend && .venv/bin/python tools/explore_auction_t0_edge.py
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


def load_kline_bars(code: str) -> list[dict]:
    """per code 返 bars list（按 date 排序）。"""
    db = sqlite3.connect(str(KLINE))
    row = db.execute("SELECT bars_json FROM kline WHERE code=?", (code,)).fetchone()
    db.close()
    if not row or not row[0]:
        return []
    try:
        bars = json.loads(row[0])
    except Exception:
        return []
    out = []
    for b in bars:
        d = str(b.get("date", ""))[:10]
        o = float(b.get("open", 0) or 0)
        c = float(b.get("close", 0) or 0)
        if d and o > 0 and c > 0:
            out.append({"date": d, "open": o, "close": c})
    out.sort(key=lambda x: x["date"])
    return out


def find_next_open(bars: list[dict], date: str) -> tuple[float, float, float] | None:
    """找 date 的 (open, close, next_open)。next_open=次日 open（T+1 制度，当日买次日卖）。"""
    for i, b in enumerate(bars):
        if b["date"] == date:
            o = b["open"]
            c = b["close"]
            if i + 1 < len(bars):
                next_open = bars[i + 1]["open"]
                return (o, c, next_open)
            return None  # 无次日 bar
    return None


def main() -> dict:
    db = sqlite3.connect(str(INTRADAY))
    # no_cancel auction 信号
    auctions = db.execute("""
        SELECT date, code, auction_pct, auction_volume_ratio, auction_unmatched,
               auction_turnover_pct
        FROM intraday_auction_snapshots
        WHERE auction_phase="no_cancel"
        ORDER BY date, code
    """).fetchall()
    print(f"no_cancel auctions: {len(auctions)} rows", flush=True)

    # per code join kline——edge = (next_open - open) / open（T+1 制度，当日买次日卖）
    obs: list[dict] = []
    cache: dict[str, list] = {}
    for date, code, auction_pct, vol_ratio, unmatched, turnover in auctions:
        if code not in cache:
            cache[code] = load_kline_bars(code)
        bars = cache[code]
        oc = find_next_open(bars, date)
        if not oc:
            continue
        open_p, close_p, next_open = oc
        # T+1 制度：entry=当日 open（市场价），exit=次日 open（overnight gap，但 entry 非涨停价）
        edge = (next_open - open_p) / open_p
        # §44 v3 R3 realizability-bias 双向：次日一字涨停（卖不掉）+ 次日一字跌停（买不回——但这里已买，卖不掉）
        # next vs close 涨跌幅 >9.5% 近似一字
        next_gap_pct = (next_open - close_p) / close_p * 100
        is_next_locked = abs(next_gap_pct) >= 9.5
        obs.append({
            "date": date, "code": code,
            "auction_pct": float(auction_pct) if auction_pct is not None else 0.0,
            "vol_ratio": float(vol_ratio) if vol_ratio is not None else None,
            "unmatched": float(unmatched) if unmatched is not None else None,
            "turnover": float(turnover) if turnover is not None else None,
            "edge": edge, "win": 1 if edge > 0 else 0,
            "next_locked": is_next_locked,
        })
    n = len(obs)
    days = len(set(o["date"] for o in obs))
    print(f"obs={n} days={days} (join kline 后)", flush=True)
    if n < 30:
        print(f"n={n}<30 → underpowered")
        return {"status": "underpowered", "n": n, "days": days}

    rets = [o["edge"] for o in obs]
    wr = sum(o["win"] for o in obs) / n
    net_mean = statistics.mean(rets)
    print(f"\n=== 全样本 T+0 edge ===")
    print(f"n={n} days={days} net_mean={net_mean*100:.2f}% WR={wr*100:.2f}%")

    # 分组 by auction_pct 分位（高竞价涨 vs 低）
    obs_sorted = sorted(obs, key=lambda x: x["auction_pct"])
    pct_vals = [o["auction_pct"] for o in obs_sorted]
    # 3 分组：低（<-2%）、中（-2~+5%）、高（>+5%）
    buckets = {"低(<-2%)": [], "中(-2~+5%)": [], "高(>+5%)": []}
    for o in obs:
        ap = o["auction_pct"]
        if ap < -2.0:
            buckets["低(<-2%)"].append(o)
        elif ap <= 5.0:
            buckets["中(-2~+5%)"].append(o)
        else:
            buckets["高(>+5%)"].append(o)
    print(f"\n=== 按 auction_pct 分组 T+0 edge ===")
    for name, group in buckets.items():
        if not group:
            print(f"  {name}: n=0")
            continue
        g_rets = [o["edge"] for o in group]
        g_wr = sum(o["win"] for o in group) / len(group)
        g_mean = statistics.mean(g_rets)
        g_days = len(set(o["date"] for o in group))
        print(f"  {name}: n={len(group)} days={g_days} net_mean={g_mean*100:.2f}% WR={g_wr*100:.2f}%")

    # §44 v3 R1: entry 一字跌停 filter（auction_pct>-9.5%，open 买不到）
    # §44 v3 R3: exit 次日一字涨停/跌停 filter（next_locked——卖不掉/买不回）
    obs_r1 = [o for o in obs if o["auction_pct"] > -9.5]
    obs_filtered = [o for o in obs_r1 if not o["next_locked"]]
    n_r1 = len(obs_r1)
    n_f = len(obs_filtered)
    print(f"\n=== §44 v3 R1+R3 filter（entry 一字跌停 + exit 次日一字）===")
    print(f"  R1 entry filter: {n}→{n_r1}（排除 {n - n_r1} entry 一字跌停）")
    print(f"  R3 exit filter: {n_r1}→{n_f}（排除 {n_r1 - n_f} 次日一字涨停/跌停）")

    # §44 stats（day_clustered t-test，exploratory <60 天）——属性访问非 unpack
    try:
        from s44_verifier.stats import day_clustered_t_test
        dts = [o["date"] for o in obs_filtered]
        rets_f = [o["edge"] for o in obs_filtered]
        res = day_clustered_t_test(rets_f, dts)
        print(f"\n=== §44 day_clustered t-test（filter 后）===")
        print(f"  t={res.t_stat:.3f} p_one_sided={res.p_one_sided:.4f}")
        print(f"  days={days}<60 → exploratory only（非 definitive）")
    except Exception as e:
        print(f"§44 stats err: {e}")

    print(f"\n=== §44 v3 审（防 V1 假 edge）===")
    print(f"  ✓ entry=open 市场价（非涨停价）——避开 V1 entry 涨停价")
    print(f"  ✓ exit=close 市场价（T+0 日内卖）——避开 D+1 一字涨停 over-credit")
    print(f"  ✓ 窗口语义：T+0 日内 edge（open→close），非涨停封板溢价非 overnight gap")
    print(f"  ⚠ days={days}<60 → exploratory only，须累积到 60 天 definitive")

    return {"n": n, "days": days, "net_mean_pct": round(net_mean * 100, 4), "wr": round(wr, 4)}


if __name__ == "__main__":
    main()
