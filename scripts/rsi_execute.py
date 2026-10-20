#!/usr/bin/env python3
"""RSI策略完整执行——从信号检测到操作建议。

最终策略v3：
- 买入: RSI(14日)<30
- 标的: 上证50ETF(510050)
- 仓位: 100%
- 止盈: +30%
- 持有: 最长20天
- 止损: 无
- 回测: 3年+64.66% 夏普1.90 回撤-7.1%

跑法：python3 scripts/rsi_execute.py
"""
import json, os, sys, subprocess, time
import numpy as np
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from strategies.rsi_timing import calculate_rsi, calc_macd, check_rsi_macd_combo, RSI_PARAMS

CST = timezone(timedelta(hours=8))
HITHINK = "/Users/lizhiwei/.nvm/versions/node/v24.21.0/bin/hithink-finance"


def get_index_data(code):
    """拉指数K线。"""
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - 60 * 86400000
    r = subprocess.run(
        [HITHINK, "index", "history", "--thscode", code,
         "--start-ms", str(start_ms), "--end-ms", str(end_ms)],
        capture_output=True, text=True, timeout=15,
    )
    try:
        d = json.loads(r.stdout)
        items = d.get("data", {}).get("item", [])
        closes = [i["close_price"] for i in items if i.get("close_price")]
        highs = [i.get("high_price", i["close_price"]) for i in items]
        return closes, highs
    except:
        return [], []


def check_bear_alignment(closes):
    """检查空头排列。"""
    if len(closes) < 20:
        return False
    ma5 = np.mean(closes[-5:])
    ma10 = np.mean(closes[-10:])
    ma20 = np.mean(closes[-20:])
    return closes[-1] < ma5 < ma10 < ma20


def check_bb_position(closes):
    """布林带位置。"""
    if len(closes) < 20:
        return 50, 0, 0
    ma20 = np.mean(closes[-20:])
    std = np.std(closes[-20:], ddof=1)
    upper = ma20 + 2 * std
    lower = ma20 - 2 * std
    cur = closes[-1]
    pos = (cur - lower) / (upper - lower) * 100 if upper != lower else 50
    return pos, upper, lower


def main():
    now = datetime.now(CST)
    if now.weekday() >= 5:
        print(f"周末: {now.strftime('%Y-%m-%d %A')}")
        return

    print(f"=== RSI策略执行 | {now.strftime('%Y-%m-%d %H:%M')} ===\n")

    # 1. 上证综指状态
    closes, highs = get_index_data("000001.SH")
    if len(closes) < 30:
        print("数据不足")
        return

    rsi = calculate_rsi(closes)
    cur = closes[-1]
    ma5 = np.mean(closes[-5:])
    ma10 = np.mean(closes[-10:])
    ma20 = np.mean(closes[-20:])
    bear = check_bear_alignment(closes)
    bb_pos, bb_upper, bb_lower = check_bb_position(closes)

    # MACD
    dif, dea, hist = calc_macd(closes)
    is_golden = dif[-1] > dea[-1]
    converging = abs(dif[-1] - dea[-1]) < abs(dif[-2] - dea[-2]) if len(dif) >= 2 else False

    # 预估金叉
    days_to_cross = None
    if not is_golden:
        diffs = [abs(dif[i] - dea[i]) for i in range(max(0, len(dif) - 10), len(dif))]
        if len(diffs) >= 2:
            shrinks = [diffs[i] - diffs[i+1] for i in range(len(diffs) - 1) if diffs[i+1] < diffs[i]]
            if shrinks and np.mean(shrinks) > 0:
                days_to_cross = int(abs(dif[-1] - dea[-1]) / np.mean(shrinks))

    print(f"【上证综指状态】")
    print(f"  价格: {cur:.0f}")
    print(f"  RSI: {rsi:.1f} {'✅<30触发' if rsi<30 else '❌未触发'}")
    print(f"  MA5={ma5:.0f} MA10={ma10:.0f} MA20={ma20:.0f}")
    print(f"  空头排列: {'✅' if bear else '❌'}")
    print(f"  布林: 上轨{bb_upper:.0f} 下轨{bb_lower:.0f} 位置{bb_pos:.0f}%")
    print(f"  MACD: DIF={dif[-1]:.1f} DEA={dea[-1]:.1f} {'✅金叉' if is_golden else '❌死叉'}")
    print(f"  收敛: {'✅' if converging else '❌'}")
    if days_to_cross:
        print(f"  预估金叉: ~{days_to_cross}个交易日")

    # 2. 因子检查
    print(f"\n【因子检查】")
    factors = []
    if rsi < 30:
        factors.append(("RSI<30", "✅", f"RSI={rsi:.0f}"))
    else:
        factors.append(("RSI<30", "❌", f"RSI={rsi:.0f}"))

    if is_golden:
        factors.append(("MACD金叉", "✅", "已金叉"))
    elif converging and days_to_cross:
        factors.append(("MACD金叉", "⏳", f"~{days_to_cross}天后"))
    else:
        factors.append(("MACD金叉", "❌", "死叉"))

    factors.append(("空头排列", "✅" if bear else "❌", ""))
    factors.append(("布林中轨下方", "✅" if bb_pos < 50 else "❌", f"位置{bb_pos:.0f}%"))

    for name, status, detail in factors:
        print(f"  {name:15s} {status} {detail}")

    triggered = sum(1 for _, s, _ in factors if s == "✅")
    print(f"  已触发: {triggered}/4")

    # 3. 操作建议
    print(f"\n【操作建议】")

    if rsi < 30 and is_golden:
        print(f"  🚨 三因子全部触发——最强买入信号")
        print(f"  买: 上证50ETF(510050)")
        print(f"  仓位: 100%")
        print(f"  止盈: +30% 持有: 最长20天")
        print(f"  预期: +13.65% WR100% (三因子历史)")
    elif rsi < 30:
        print(f"  ⏳ RSI已触发({rsi:.0f}) MACD未金叉")
        print(f"  方案A(激进): 现在买上证50ETF")
        print(f"    RSI={rsi:.0f}极端超卖 预期+7.82% WR92%")
        if bear:
            print(f"    +空头排列✅ 预期+11% WR100%")
        print(f"  方案B(稳健): 等MACD金叉确认")
        if days_to_cross:
            print(f"    预估{days_to_cross}个交易日后金叉")
        print(f"    金叉后: +9.53% WR100% (RSI+MACD金叉)")
        print(f"  方案C(最稳): 等三因子全部触发")
        print(f"    RSI+MACD金叉+空头排列: +13.65% WR100%")
    else:
        print(f"  ❌ RSI未触发——等待RSI<30")

    # 4. 上证50ETF状态
    print(f"\n【上证50ETF(510050)】")
    etf_closes, etf_highs = get_index_data("000016.SH")
    if len(etf_closes) >= 15:
        etf_rsi = calculate_rsi(etf_closes)
        etf_cur = etf_closes[-1]
        print(f"  上证50指数: {etf_cur:.0f} RSI={etf_rsi:.0f} {'✅<30' if etf_rsi<30 else '❌'}")
        print(f"  上证50ETF(510050) ≈ 上证50指数/1000")
        print(f"  ETF价格≈{etf_cur/1000:.3f}元")
        if etf_rsi < 30:
            print(f"  → 上证50ETF RSI也触发 ✅")
            print(f"  → 买入100股≈{etf_cur/1000*100:.0f}元")

    # 5. 持仓状态
    print(f"\n【持仓状态】")
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:8900/api/portfolio", timeout=5) as r:
            portfolio = json.loads(r.read())["data"]
        for h in portfolio["holdings"]:
            print(f"  {h['name']:8s} {h['pnl_pct']:+.1f}% 市值{h['market_value']:.0f}")
        t = portfolio["totals"]
        print(f"  总: 市值{t['market_value']:.0f} 浮亏{t['pnl_pct']:+.1f}%")
    except:
        print("  API不可用")

    # 6. 关键价位
    print(f"\n【关键价位】")
    print(f"  减仓信号: 上证站上{ma20:.0f}(MA20)")
    print(f"  清仓信号: 上证跌破3707(年内最低)")
    print(f"  RSI退出: RSI>60")
    print(f"  止盈: +30%(ETF买入价×1.3)")
    print(f"  当前: {cur:.0f} 距MA20 {(cur-ma20)/ma20*100:+.1f}%")


if __name__ == "__main__":
    main()
