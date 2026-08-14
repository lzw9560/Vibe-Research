# -*- coding: utf-8 -*-
"""回测：游资接力净流出过滤能否提高胜率。

Step 1: 新浪 API 拉日K → 计算 vol_ratio / amount / 次日收益
Step 2: 东财 datacenter API 拉龙虎榜 → 计算游资净额
Step 3: 分组对比
"""
import sqlite3, urllib.request, json, time, sys, os

DB = "/Users/lizhiwei/project/code/stock/Vibe-Research/.vibe-research/gene_scores.db"
CACHE_FILE = "/tmp/backtest_kline_cache.json"

def fetch_klines_sina(code, datalen=250):
    prefix = "sh" if code.startswith("6") else "sz"
    url = (f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"CN_MarketData.getKLineData?symbol={prefix}{code}&scale=240&ma=no&datalen={datalen}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                "Referer": "https://finance.sina.com.cn"})
    for attempt in range(3):
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read())
            return [{"date": d["day"][:10], "open": float(d["open"]), "high": float(d["high"]),
                     "low": float(d["low"]), "close": float(d["close"]), "vol": float(d["volume"])}
                    for d in data]
        except Exception as e:
            if attempt < 2:
                time.sleep(3)
            else:
                print(f"  sina error {code}: {e}", file=sys.stderr)
                return []

def fetch_dragon_tiger(date_str):
    """东财 datacenter: 取指定日期所有龙虎榜买卖明细 → {code: net_flow_yuan}"""
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
           f"reportName=RPT_BILLBOARD_DAILYDETAILSBUY&columns=ALL&"
           f"filter=(TRADE_DATE%3E%3D'{date_str}')(TRADE_DATE%3C%3D'{date_str}')&"
           f"pageNumber=1&pageSize=500&sortColumns=TRADE_DATE&sortTypes=-1&source=WEB&client=WEB")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                "Referer": "https://data.eastmoney.com/"})
    buy_rows = []
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        buy_rows = data.get("result", {}).get("data", []) or []
    except Exception as e:
        print(f"  dt buy error {date_str}: {e}", file=sys.stderr)
    
    url2 = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
            f"reportName=RPT_BILLBOARD_DAILYDETAILSSELL&columns=ALL&"
            f"filter=(TRADE_DATE%3E%3D'{date_str}')(TRADE_DATE%3C%3D'{date_str}')&"
            f"pageNumber=1&pageSize=500&sortColumns=TRADE_DATE&sortTypes=-1&source=WEB&client=WEB")
    req2 = urllib.request.Request(url2, headers={"User-Agent": "Mozilla/5.0",
                                                 "Referer": "https://data.eastmoney.com/"})
    sell_rows = []
    try:
        resp2 = urllib.request.urlopen(req2, timeout=15)
        data2 = json.loads(resp2.read())
        sell_rows = data2.get("result", {}).get("data", []) or []
    except Exception as e:
        print(f"  dt sell error {date_str}: {e}", file=sys.stderr)
    
    # Aggregate net flow per code
    code_net = {}
    for r in buy_rows + sell_rows:
        code = r.get("SECURITY_CODE", "")
        try:
            net = float(r.get("NET")) if r.get("NET") is not None else 0.0
        except (TypeError, ValueError):
            net = 0.0
        code_net[code] = code_net.get(code, 0.0) + net
    return code_net  # {code: net_flow_yuan}

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
        "SELECT date, code, name, total_score FROM gene_scores WHERE qualify=1 ORDER BY date DESC"
    ).fetchall()
    conn.close()
    print(f"Total qualify=1 pairs: {len(rows)}")
    codes = list(set(r[1] for r in rows))
    print(f"Unique codes: {len(codes)}")
    
    # Step 1: Fetch klines (with cache)
    kline_cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            kline_cache = json.load(f)
        print(f"Loaded kline cache: {len(kline_cache)} codes")
    
    for i, code in enumerate(codes):
        if code in kline_cache:
            continue
        bars = fetch_klines_sina(code)
        kline_cache[code] = bars
        print(f"  [{i+1}/{len(codes)}] {code}: {len(bars)} bars", file=sys.stderr)
        time.sleep(1.5)
    
    with open(CACHE_FILE, "w") as f:
        json.dump(kline_cache, f)
    
    # Build samples with kline data
    samples = []
    for date, code, name, gene_score in rows:
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
        amount_yi = round(bar["vol"] * bar["close"] / 1e8, 4)
        next_return = round((next_bar["close"] - bar["close"]) / bar["close"] * 100, 2)
        samples.append({
            "date": date, "code": code, "name": name,
            "gene_score": gene_score,
            "vol_ratio": vol_ratio, "amount_yi": amount_yi,
            "close": bar["close"],
            "next_return": next_return,
            "next_date": next_bar["date"],
        })
    print(f"Valid kline samples: {len(samples)}")
    
    # Step 2: Fetch dragon tiger data for each distinct date
    distinct_dates = sorted(set(s["date"] for s in samples))
    print(f"Distinct dates: {len(distinct_dates)}")
    dt_cache = {}
    for i, d in enumerate(distinct_dates):
        dt_cache[d] = fetch_dragon_tiger(d)
        n_codes = len(dt_cache[d])
        print(f"  [{i+1}/{len(distinct_dates)}] {d}: {n_codes} codes on dragon tiger", file=sys.stderr)
        time.sleep(1.0)
    
    # Match dragon tiger data to samples
    for s in samples:
        dt_data = dt_cache.get(s["date"], {})
        net_yuan = dt_data.get(s["code"])
        if net_yuan is not None:
            s["dt_net_wan"] = round(net_yuan / 10000.0, 1)  # 元 → 万元
            s["dt_on_board"] = True
        else:
            s["dt_net_wan"] = None
            s["dt_on_board"] = False
    
    # Step 3: Stats
    def stats(group, label):
        if not group:
            print(f"  {label}: 0 samples")
            return
        n = len(group)
        wins = sum(1 for s in group if s["next_return"] > 0)
        avg_ret = sum(s["next_return"] for s in group) / n
        win_rate = wins / n * 100
        win_rets = [s["next_return"] for s in group if s["next_return"] > 0]
        loss_rets = [s["next_return"] for s in group if s["next_return"] <= 0]
        avg_win = sum(win_rets) / len(win_rets) if win_rets else 0
        avg_loss = sum(loss_rets) / len(loss_rets) if loss_rets else 0
        expectancy = (win_rate / 100 * avg_win) + ((100 - win_rate) / 100 * avg_loss)
        print(f"  {label}: n={n:3d}  win={win_rate:5.1f}%  avg={avg_ret:+6.2f}%  exp={expectancy:+.2f}%  avgWin={avg_win:+.2f}  avgLoss={avg_loss:+.2f}")
    
    print("\n=== 全量基准 ===")
    stats(samples, "All (no filter)")
    
    print("\n=== 龙虎榜游资净额分组 ===")
    on_board = [s for s in samples if s["dt_on_board"]]
    not_board = [s for s in samples if not s["dt_on_board"]]
    stats(on_board, "on dragon tiger board")
    stats(not_board, "NOT on board")
    
    stats([s for s in on_board if s["dt_net_wan"] >= 0], "dt_net >= 0 (游资净流入)")
    stats([s for s in on_board if s["dt_net_wan"] < 0], "dt_net < 0 (游资净流出)")
    
    print("\n=== 游资净流出过滤效果 ===")
    # If we filter out (remove) dt_net < 0
    filtered_in = [s for s in samples if not s["dt_on_board"] or s["dt_net_wan"] >= 0]
    filtered_out = [s for s in on_board if s["dt_net_wan"] < 0]
    stats(filtered_in, "keep (not on board OR dt_net >= 0)")
    stats(filtered_out, "removed (on board AND dt_net < 0)")
    
    print("\n=== 明细：龙虎榜上榜股 ===")
    for s in sorted(on_board, key=lambda x: x["dt_net_wan"]):
        print(f"  {s['date']} {s['code']} {s['name']:6s} dt_net={s['dt_net_wan']:+8.1f}万 → next={s['next_return']:+6.2f}% vr={s['vol_ratio']}")

if __name__ == "__main__":
    main()
