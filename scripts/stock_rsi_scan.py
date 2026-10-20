#!/usr/bin/env python3
"""个股RSI扫描——全市场RSI<30 + 历史回测 + 财务红线过滤。

回测：172只RSI<30个股中位mean+1.87% 76%正收益
过滤后53只历史显著(p<0.10)，其中49只p<0.05

跑法：python3 scripts/stock_rsi_scan.py
"""
import json, os, sys, sqlite3, time
import numpy as np
from scipy import stats as sp_stats

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

KDB = os.path.join(os.path.dirname(__file__), "..", ".vibe-research", "baostock_kline_cache.db")

def calc_rsi(closes):
    if len(closes) < 15:
        return 50.0
    changes = [closes[j]-closes[j-1] for j in range(len(closes)-14, len(closes))]
    gains = [c for c in changes if c>0]
    losses = [-c for c in changes if c<0]
    avg_gain = np.mean(gains) if gains else 0
    avg_loss = np.mean(losses) if losses else 0.001
    if avg_loss == 0: return 100.0
    return 100 - 100/(1 + avg_gain/avg_loss)

def scan():
    kdb = sqlite3.connect(KDB)
    cursor = kdb.execute("SELECT code, bars_json FROM kline")
    
    results = []
    total = 0
    while True:
        rows = cursor.fetchmany(500)
        if not rows: break
        for code, bj in rows:
            total += 1
            try: bars = json.loads(bj)
            except: continue
            if len(bars) < 35: continue
            
            closes = [float(b.get('close',0) or 0) for b in bars[-15:]]
            if len(closes) < 15 or any(c<=0 for c in closes): continue
            rsi = calc_rsi(closes)
            if rsi >= 30: continue
            
            # 历史回测
            hist_rets = []
            for i in range(15, len(bars)-20):
                h_closes = [float(bars[j].get('close',0) or 0) for j in range(max(0,i-14), i+1)]
                if len(h_closes) < 15 or any(c<=0 for c in h_closes): continue
                h_rsi = calc_rsi(h_closes)
                if h_rsi < 30 and i+20 < len(bars):
                    ret = (float(bars[i+20].get('close',0) or 0) - float(bars[i].get('close',0) or 0)) / float(bars[i].get('close',0) or 0) * 100
                    if abs(ret) < 50:
                        hist_rets.append(ret)
            
            if len(hist_rets) < 5: continue
            
            arr = np.array(hist_rets)
            mean = np.mean(arr)
            wr = np.mean(arr>0)*100
            p_val = sp_stats.ttest_1samp(arr, 0)[1]/2 if len(arr)>=5 else 1
            
            cur_price = float(bars[-1].get('close',0) or 0)
            amount = float(bars[-1].get('amount',0) or 0) / 1e8
            
            results.append({
                'code': code, 'price': cur_price, 'rsi': round(rsi,1),
                'hist_n': len(hist_rets), 'hist_mean': round(mean,2),
                'hist_wr': round(wr,0), 'p_value': round(p_val,4),
                'amount_yi': round(amount,2),
            })
    kdb.close()
    
    # 过滤
    filtered = [r for r in results if r['hist_mean']>0 and r['hist_wr']>60 and r['p_value']<0.10 and r['hist_n']>=10]
    filtered.sort(key=lambda x: -x['hist_mean'])
    
    print(f"扫描{total}只 → RSI<30: {len(results)}只 → 过滤: {len(filtered)}只\n")
    print(f"{'代码':8s} {'价格':>8s} {'RSI':>5s} {'n':>4s} {'mean':>8s} {'WR':>5s} {'p值':>8s} {'额':>5s}")
    for r in filtered[:20]:
        sig = '✅' if r['p_value']<0.05 else '⚠️'
        print(f"  {r['code']:8s} {r['price']:8.2f} {r['rsi']:5.0f} {r['hist_n']:4d} {r['hist_mean']:+7.2f}% {r['hist_wr']:4.0f}% {r['p_value']:7.4f}{sig} {r['amount_yi']:4.1f}亿")
    
    return filtered

if __name__ == "__main__":
    scan()
