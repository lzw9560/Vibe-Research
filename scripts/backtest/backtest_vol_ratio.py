# -*- coding: utf-8 -*-
"""回测 v2：R2 加入 vol_ratio/amount 硬过滤能否提高胜率。

数据源：新浪财经 K 线 API（quotes_service/api/json_v2.php）。
样本：gene_scores.db 中 qualify=1 的 93 个 (date,code) 对。
方法：拉日K → 计算 vol_ratio / amount_yi(=vol*close近似) / 次日收益 → 分组对比。
"""
import sqlite3, urllib.request, json, time, sys

DB = "/Users/lizhiwei/project/code/stock/Vibe-Research/.vibe-research/gene_scores.db"

def fetch_klines_sina(code: str, datalen=250) -> list[dict]:
    """新浪日K，返回 [{day, open, high, low, close, volume}]"""
    prefix = "sh" if code.startswith("6") else "sz"
    url = (f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"CN_MarketData.getKLineData?symbol={prefix}{code}&scale=240&ma=no&datalen={datalen}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                "Referer": "https://finance.sina.com.cn"})
    for attempt in range(3):
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            raw = resp.read()
            data = json.loads(raw)
            bars = []
            for d in data:
                bars.append({
                    "date": d["day"][:10],
                    "open": float(d["open"]),
                    "high": float(d["high"]),
                    "low": float(d["low"]),
                    "close": float(d["close"]),
                    "vol": float(d["volume"]),  # 股
                })
            return bars
        except Exception as e:
            if attempt < 2:
                time.sleep(3)
            else:
                print(f"  sina fetch error {code}: {e}", file=sys.stderr)
                return []

def calc_vol_ratio(bars, idx):
    if idx < 5:
        return None
    prev_vols = [bars[i]["vol"] for i in range(idx - 5, idx)]
    avg_prev = sum(prev_vols) / len(prev_vols)
    if avg_prev <= 0:
        return None
    return round(bars[idx]["vol"] / avg_prev, 2)

def main():
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT date, code, name, total_score, factor_seal_rate, factor_premium_rate, factor_red_rate "
        "FROM gene_scores WHERE qualify=1 ORDER BY date DESC"
    ).fetchall()
    conn.close()
    print(f"Total qualify=1 pairs: {len(rows)}")
    
    codes = list(set(r[1] for r in rows))
    print(f"Unique codes: {len(codes)}")
    
    kline_cache = {}
    for i, code in enumerate(codes):
        bars = fetch_klines_sina(code)
        kline_cache[code] = bars
        print(f"  [{i+1}/{len(codes)}] {code}: {len(bars)} bars", file=sys.stderr)
        time.sleep(1.5)  # 限流
    
    samples = []
    for date, code, name, gene_score, seal_rate, prem_rate, red_rate in rows:
        bars = kline_cache.get(code, [])
        idx = None
        for j, b in enumerate(bars):
            if b["date"] == date:
                idx = j
                break
        if idx is None or idx + 1 >= len(bars):
            continue
        bar = bars[idx]
        next_bar = bars[idx + 1]
        
        vol_ratio = calc_vol_ratio(bars, idx)
        # amount 近似 = vol * close（单位：元），转亿
        amount_yi = round(bar["vol"] * bar["close"] / 1e8, 4)
        next_return = round((next_bar["close"] - bar["close"]) / bar["close"] * 100, 2)
        
        samples.append({
            "date": date, "code": code, "name": name,
            "gene_score": gene_score, "seal_rate": seal_rate,
            "prem_rate": prem_rate, "red_rate": red_rate,
            "vol_ratio": vol_ratio, "amount_yi": amount_yi,
            "close": bar["close"],
            "next_return": next_return,
            "next_date": next_bar["date"],
        })
    
    print(f"\nValid samples: {len(samples)}")
    if not samples:
        print("No valid samples — kline fetch failed for all codes")
        return
    
    def stats(group, label):
        if not group:
            print(f"  {label}: 0 samples")
            return
        n = len(group)
        wins = sum(1 for s in group if s["next_return"] > 0)
        losses = sum(1 for s in group if s["next_return"] <= 0)
        avg_ret = sum(s["next_return"] for s in group) / n
        win_rate = wins / n * 100
        median_ret = sorted([s["next_return"] for s in group])[n // 2]
        # Mean win/loss
        win_rets = [s["next_return"] for s in group if s["next_return"] > 0]
        loss_rets = [s["next_return"] for s in group if s["next_return"] <= 0]
        avg_win = sum(win_rets) / len(win_rets) if win_rets else 0
        avg_loss = sum(loss_rets) / len(loss_rets) if loss_rets else 0
        # Expectancy
        expectancy = (win_rate / 100 * avg_win) + ((100 - win_rate) / 100 * avg_loss)
        print(f"  {label}: n={n:3d}  win={win_rate:5.1f}%  avg={avg_ret:+6.2f}%  med={median_ret:+6.2f}%  avgWin={avg_win:+.2f}  avgLoss={avg_loss:+.2f}  exp={expectancy:+.2f}%")
    
    print("\n=== 全量基准 ===")
    stats(samples, "All (no filter)")
    
    print("\n=== 量比 vol_ratio 分组 ===")
    vr_known = [s for s in samples if s["vol_ratio"] is not None]
    stats(vr_known, "vr known")
    stats([s for s in vr_known if s["vol_ratio"] >= 1.5], "vr >= 1.5 (proposed)")
    stats([s for s in vr_known if s["vol_ratio"] < 1.5], "vr < 1.5 (filtered out)")
    stats([s for s in vr_known if s["vol_ratio"] >= 1.0], "vr >= 1.0")
    stats([s for s in vr_known if s["vol_ratio"] < 1.0], "vr < 1.0")
    stats([s for s in vr_known if s["vol_ratio"] >= 2.0], "vr >= 2.0")
    
    print("\n=== 成交额 amount_yi 分组 ===")
    stats([s for s in samples if s["amount_yi"] is not None], "amt known")
    stats([s for s in samples if s["amount_yi"] >= 10], "amt >= 10亿 (proposed)")
    stats([s for s in samples if s["amount_yi"] < 10], "amt < 10亿 (filtered out)")
    stats([s for s in samples if s["amount_yi"] >= 5], "amt >= 5亿")
    stats([s for s in samples if s["amount_yi"] >= 8], "amt >= 8亿")
    
    print("\n=== 组合过滤 ===")
    stats([s for s in vr_known if s["vol_ratio"] >= 1.5 and s["amount_yi"] >= 10], "vr>=1.5 & amt>=10亿")
    stats([s for s in vr_known if s["vol_ratio"] >= 1.0 and s["amount_yi"] >= 5], "vr>=1.0 & amt>=5亿")
    stats([s for s in vr_known if not (s["vol_ratio"] >= 1.5 and s["amount_yi"] >= 10)], "NOT(vr>=1.5 & amt>=10)")
    
    print("\n=== 明细（按次日收益降序）===")
    for s in sorted(samples, key=lambda x: x["next_return"], reverse=True):
        vr = f"{s['vol_ratio']:.2f}" if s["vol_ratio"] is not None else "  N/A"
        print(f"  {s['date']} {s['code']} {s['name']:6s} gene={s['gene_score']:5.1f} vr={vr:>5} amt={s['amount_yi']:7.2f}亿 close={s['close']:6.2f} → next={s['next_return']:+6.2f}% ({s['next_date']})")

if __name__ == "__main__":
    main()
