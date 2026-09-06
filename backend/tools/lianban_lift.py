# -*- coding: utf-8 -*-
# 连板 verdict (2026-09-06, ths_limit_up_pool 42天/2760 obs, net-profit-verify):
#   all net-WR 31.63% | 首板 0.986x null | 2连板 1.073x 弱 | 3+连板 1.004x null | 连板(2+) 1.044x 弱<2x
# 连板 D+1 path 无 tradeable edge(<2x). Hua'an+14.6%/92.3%win 是连板-riding 策略(特定入场/退出 gross 非 net)
# 非本 D+1 path 框架——不同口径不可直接比, 需另策略 harness 才测连板-riding。
"""S158: 连板（high_days）§44 维度——ths_limit_up_pool(date) 42 天覆盖。
文献 Hua'an 2026: 连板 tail 2.4% 赚 14.5% 利润 +14.6% 92.3% win（强但稀）。
复用 day_paired per-T top-vs-all + net-profit-verify（S155/S156 教训）。"""
import json, re, sqlite3, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]  # S163 R3: repo root，不硬编码绝对路径
sys.path.insert(0, str(ROOT / "backend"))
from data.sources.eastmoney import ths_limit_up_pool
from strategies.kline_returns import simulate_holding, _is_unbuyable_next_bar

KLINE = ROOT / ".vibe-research" / "baostock_kline_cache.json"
DB = ROOT / ".vibe-research" / "gene_scores.db"
LB_CACHE = ROOT / ".vibe-research" / "ths_lb_cache.json"
ROUND_TRIP_COST = 0.70
PARAMS = (-3.0, 8.0, 3)

def parse_boards(high_days: str) -> int:
    """'3天3板'→3, '2天2板'→2, 首板/空→1。"""
    m = re.search(r"(\d+)\s*板", str(high_days or ""))
    return int(m.group(1)) if m else 1

def fetch_lb(date_compact):
    cache = json.loads(LB_CACHE.read_text()) if LB_CACHE.exists() else {}
    if date_compact in cache: return cache[date_compact]
    try:
        rows = ths_limit_up_pool(date_compact)
        time.sleep(0.5)
        out = [{"code": str(r.get("code") or "").zfill(6), "boards": parse_boards(r.get("high_days"))} for r in rows if r.get("code")]
        cache[date_compact] = out
        LB_CACHE.write_text(json.dumps(cache, ensure_ascii=False))
        return out
    except Exception as e:
        print(f"  lb {date_compact} ERR {repr(e)[:80]}", flush=True); return []

def main():
    cache = json.loads(KLINE.read_bytes())
    conn = sqlite3.connect(str(DB), timeout=10)
    try:
        em_dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT date FROM gene_scores WHERE data_source='eastmoney_live' ORDER BY date").fetchall()]
    finally:
        conn.close()
    print(f"dates={len(em_dates)}", flush=True)

    obs = []
    for di, D in enumerate(em_dates):
        pool = fetch_lb(D.replace("-", ""))
        if not pool: continue
        print(f"  [{di+1}/{len(em_dates)}] {D}: {len(pool)} 涨停股", flush=True)
        for s in pool:
            code = s["code"]; bars = cache.get(code)
            if not bars: continue
            d_idx = next((i for i, b in enumerate(bars) if str(b["date"])[:10] == D), None)
            if d_idx is None or d_idx + 1 >= len(bars): continue
            if _is_unbuyable_next_bar(bars[d_idx + 1]): continue
            sim = simulate_holding(bars, D, *PARAMS)
            if sim is None: continue
            net = sim["return_pct"] - ROUND_TRIP_COST
            obs.append({"D": D, "code": code, "boards": s["boards"],
                        "net": net, "win": 1 if net > 0 else 0})

    if len(obs) < 30:
        print(f"n={len(obs)} <30 探索性"); return
    all_wins = sum(o["win"] for o in obs); wr_all = all_wins / len(obs)
    print(f"\nobs={len(obs)} days={len(set(o['D'] for o in obs))} | all net-WR(涨停股 D+1): {wr_all*100:.2f}%")
    # 连板分布
    from collections import Counter
    dist = Counter(o["boards"] for o in obs)
    print(f"连板分布: {dict(sorted(dist.items()))}\n")

    for name, pred in [("首板(boards==1)", lambda o: o["boards"] == 1),
                       ("2连板", lambda o: o["boards"] == 2),
                       ("3+连板", lambda o: o["boards"] >= 3),
                       ("连板(2+)", lambda o: o["boards"] >= 2)]:
        tw, tn = 0, 0
        for D in set(o["D"] for o in obs):
            day = [o for o in obs if o["D"] == D]
            top = [o for o in day if pred(o)]
            tw += sum(o["win"] for o in top); tn += len(top)
        if not tn: print(f"  {name}: n=0"); continue
        wr = tw / tn; lift = wr / wr_all if wr_all else 0
        st = "VALIDATED" if lift >= 2 else ("未validated" if lift >= 1 else "劣于随机")
        print(f"  {name}: net-WR {wr*100:.2f}% (n={tn}) vs all {wr_all*100:.2f}% | net lift={lift:.3f}x {st}")

if __name__ == "__main__":
    main()
