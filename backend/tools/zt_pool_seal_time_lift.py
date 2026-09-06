# -*- coding: utf-8 -*-
# ⚠️ §44 v2 窗口caveat（2026-09-06）：以下 verdict 在 D+1-开盘→D+4 path 窗口（隔夜正之后的反转负段，entry=D+1开盘=gap 之后），非绝对无 edge——是"对窗口无 selection edge"。隔夜 gap（D收→D+1开 +1.15%）是真事件 edge 但薄/不可选/部分不可交易。见 S159 spec + memory s44-quant-validation-loop。
# S156 verdict (2026-09-06, 13 days/798 obs, zt_pool exact seal time + net-profit-verify):
#   all net-WR 23.93% | seal_amount 1.004x null | early_lock 1.102x weak | late_lock 0.663x 劣于随机
#   秒板 1.312x 唯一 net 弱正(<2x, n=121/13d modest, hint 非 tradeable) | broken 0.988x null
# §44 verdict 用更好数据确认; 秒板 hint 待 n 涨后复验(zt_pool 每日+1 day coverage)
# 防封: 当前 akshare+cache+2s sleep 低量一次性(13 call); productionize 改 eastmoney_get route(push2ex URL)
"""S156: zt_pool 历史 re-test 封单量+封板时间+秒板 net-profit-verify。
复用 S155 net 逻辑（simulate_holding+unbuyable+0.70%cost+top-vs-all）+ zt_pool 精确首封/封板资金。
signal_date=D（涨停日，feature D close 已知），entry=D+1 open（续涨/缺口验证）。"""
import json, sqlite3, sys, time
from pathlib import Path
from collections import defaultdict
ROOT = Path(__file__).resolve().parents[2]  # S163 R3: repo root，不硬编码绝对路径
sys.path.insert(0, str(ROOT / "backend"))
from strategies.kline_returns import simulate_holding, _is_unbuyable_next_bar

KLINE_CACHE = ROOT / ".vibe-research" / "baostock_kline_cache.json"
DB = ROOT / ".vibe-research" / "gene_scores.db"
ZT_CACHE = ROOT / ".vibe-research" / "zt_pool_hist_cache.json"
ROUND_TRIP_COST = 0.70
PARAMS = (-3.0, 8.0, 3)

def fetch_zt_pool(date_compact):  # YYYYMMDD
    """akstock zt_pool（push2ex），带 cache + 礼貌 sleep + try/except。生产化改 eastmoney_get route。"""
    cache = {}
    if ZT_CACHE.exists():
        cache = json.loads(ZT_CACHE.read_text())
    if date_compact in cache:
        return cache[date_compact]
    import akshare as ak
    try:
        df = ak.stock_zt_pool_em(date=date_compact)
        time.sleep(2.0)  # 礼貌防封
        rows = []
        for _, r in df.iterrows():
            rows.append({
                "code": str(r["代码"]).zfill(6),
                "seal_amount": float(r.get("封板资金") or 0),
                "first_lock": str(r.get("首次封板时间") or ""),
                "last_lock": str(r.get("最后封板时间") or ""),
                "turnover": float(r.get("换手率") or 0),
                "float_mv": float(r.get("流通市值") or 0),
            })
        cache[date_compact] = rows
        ZT_CACHE.write_text(json.dumps(cache, ensure_ascii=False))
        return rows
    except Exception as e:
        print(f"  zt_pool {date_compact} ERR: {repr(e)[:120]}", flush=True)
        return []

def _time_hhmmss(t: str) -> str:
    """首封时间 → HHMMSS（比较用）。可能 '0930' / '09:30:00' / '093000' 等格式。"""
    digits = "".join(c for c in (t or "") if c.isdigit())
    return (digits + "000000")[:6]

def main(smoke_days=None):
    cache = json.loads(KLINE_CACHE.read_bytes())
    conn = sqlite3.connect(str(DB), timeout=10)
    try:
        em_dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT date FROM gene_scores WHERE data_source='eastmoney_live' ORDER BY date").fetchall()]
    finally:
        conn.close()
    if smoke_days:
        em_dates = em_dates[:smoke_days]
    print(f"dates={len(em_dates)} cost={ROUND_TRIP_COST}% params={PARAMS}", flush=True)

    obs = []  # {D, code, seal_amount, first_lock, is_early, is_late, is_miaoban, is_broken, net, win}
    for di, D in enumerate(em_dates):
        dc = D.replace("-", "")
        pool = fetch_zt_pool(dc)
        if not pool: continue
        print(f"  [{di+1}/{len(em_dates)}] {D}: {len(pool)} 涨停股", flush=True)
        for s in pool:
            code = s["code"]
            bars = cache.get(code)
            if not bars: continue
            # signal_date=D, entry=D+1 open
            d_idx = next((i for i,b in enumerate(bars) if str(b["date"])[:10] == D), None)
            if d_idx is None or d_idx+1 >= len(bars): continue
            if _is_unbuyable_next_bar(bars[d_idx+1]): continue  # D+1 一字板不可买
            sim = simulate_holding(bars, D, *PARAMS)
            if sim is None: continue
            net = sim["return_pct"] - ROUND_TRIP_COST
            fl = _time_hhmmss(s["first_lock"])
            ll = _time_hhmmss(s["last_lock"])
            obs.append({"D": D, "code": code, "seal_amount": s["seal_amount"],
                        "first_lock": fl, "is_early": fl <= "100000", "is_late": fl > "140000",
                        "is_miaoban": fl <= "093100", "is_broken": fl != ll and ll != "000000",
                        "net": net, "win": 1 if net > 0 else 0})

    if len(obs) < 30:
        print(f"n={len(obs)} < 30 探索性"); return
    print(f"\nobs={len(obs)} days={len(set(o['D'] for o in obs))}")
    all_wins = sum(o["win"] for o in obs); all_n = len(obs)
    wr_all = all_wins/all_n
    print(f"all net-WR (涨停股 universe, D+1 entry): {wr_all*100:.2f}% (n={all_n})\n")

    def lift_for(pred_key, is_quintile=False):
        top_wins, top_n = 0, 0
        for D in set(o["D"] for o in obs):
            day = [o for o in obs if o["D"] == D]
            if len(day) < 5: continue
            if is_quintile:
                ds = sorted(day, key=lambda o: o[pred_key])
                q = max(1, len(ds)//5)
                top = ds[-q:]
            else:
                top = [o for o in day if o[pred_key]]
            top_wins += sum(o["win"] for o in top); top_n += len(top)
        if not top_n: return None
        wr = top_wins/top_n
        return wr, top_n, wr/wr_all if wr_all else 0

    for name, key, q in [("seal_amount(top quintile)", "seal_amount", True),
                         ("early_lock(首封≤10:00)", "is_early", False),
                         ("late_lock(首封>14:00)", "is_late", False),
                         ("秒板(首封≤09:31)", "is_miaoban", False),
                         ("broken(首封≠末封)", "is_broken", False)]:
        r = lift_for(key, q)
        if r is None:
            print(f"  {name}: n=0"); continue
        wr, n, lift = r
        state = "VALIDATED" if lift>=2 else ("未validated" if lift>=1 else "劣于随机")
        print(f"  {name}: net-WR {wr*100:.2f}% (n={n}) vs all {wr_all*100:.2f}% | net lift={lift:.3f}x {state}")

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", type=int, default=0)
    a = ap.parse_args()
    main(smoke_days=a.smoke or None)
