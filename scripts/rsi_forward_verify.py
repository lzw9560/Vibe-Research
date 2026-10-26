#!/usr/bin/env python3
"""RSI策略实盘前向验证——记录每次RSI<30触发+60天后验证收益。

回测预期：mean+7.82% WR92% 95%CI[+5.46%, +10.12%]
如果实盘结果落在CI内 → edge延续
如果实盘结果显著低于CI → edge衰减/失效

跑法：python3 scripts/rsi_forward_verify.py
"""
import json
import os
import sys
import subprocess
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from strategies.rsi_timing import calculate_rsi, RSI_PARAMS

CST = timezone(timedelta(hours=8))
HITHINK = "/Users/lizhiwei/.nvm/versions/node/v24.21.0/bin/hithink-finance"
TRACK_FILE = "/tmp/rsi_forward_track.json"


def load_track():
    if os.path.exists(TRACK_FILE):
        with open(TRACK_FILE) as f:
            return json.load(f)
    return {"trades": [], "settled": []}


def save_track(track):
    with open(TRACK_FILE, "w") as f:
        json.dump(track, f, indent=2, ensure_ascii=False)


def main():
    now = datetime.now(CST)
    if now.weekday() >= 5:
        print(f"周末跳过: {now.strftime('%Y-%m-%d %A')}")
        return

    track = load_track()
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - 80 * 86400000  # 近80天

    # 检查新触发
    new_triggers = 0
    for code, params in RSI_PARAMS["indices"].items():
        if not params.get("p") or params["p"] > 0.01:
            continue  # 只跟踪统计显著的(上证/创业板/深成/中证500)

        r = subprocess.run(
            [HITHINK, "index", "history", "--thscode", code,
             "--start-ms", str(start_ms), "--end-ms", str(end_ms)],
            capture_output=True, text=True, timeout=15,
        )
        try:
            d = json.loads(r.stdout)
            items = d.get("data", {}).get("item", [])
            closes = [i["close_price"] for i in items if i.get("close_price")]
            if len(closes) < 20:
                continue
        except Exception:
            continue

        # 检查最近3天是否有RSI<30触发
        for i in range(max(15, len(closes) - 3), len(closes)):
            if i >= len(closes):
                continue
            window = closes[max(0, i - 14):i + 1]
            if len(window) < 15:
                continue
            rsi = calculate_rsi(window)
            date_str = datetime.fromtimestamp(items[i]["date_ms"] / 1000).strftime("%Y-%m-%d")

            if rsi < params["threshold"]:
                # 检查是否已记录
                exists = any(
                    t["index"] == code and t["trigger_date"] == date_str
                    for t in track["trades"]
                )
                if not exists:
                    buy_price = closes[i]
                    track["trades"].append({
                        "index": code,
                        "index_name": params["name"],
                        "trigger_date": date_str,
                        "trigger_rsi": round(rsi, 1),
                        "buy_price": buy_price,
                        "expected_mean": params["mean"],
                        "expected_wr": params["wr"],
                        "hold_days": 60,
                        "status": "open",
                    })
                    new_triggers += 1
                    print(f"新触发: {params['name']} {date_str} RSI={rsi:.0f} 买入={buy_price:.0f}")

    # 按指数分组批量拉取K线（避免N笔×4s的超时）
    index_cache = {}  # thscode -> (items, closes)
    for code in set(t["index"] for t in track["trades"] if t["status"] == "open"):
        r = subprocess.run(
            [HITHINK, "index", "history", "--thscode", code,
             "--start-ms", str(start_ms), "--end-ms", str(end_ms)],
            capture_output=True, text=True, timeout=15,
        )
        try:
            d = json.loads(r.stdout)
            items = d.get("data", {}).get("item", [])
            closes = [i["close_price"] for i in items if i.get("close_price")]
            index_cache[code] = (items, closes)
        except Exception:
            index_cache[code] = ([], [])

    # 检查已记录的交易是否到期（60个交易日后）
    settled_count = 0
    for t in track["trades"]:
        if t["status"] != "open":
            continue

        if t["index"] not in index_cache:
            continue
        items, closes = index_cache[t["index"]]
        if not closes:
            continue

        # 找买入日
        buy_idx = None
        for i, item in enumerate(items):
            dt = datetime.fromtimestamp(item["date_ms"] / 1000).strftime("%Y-%m-%d")
            if dt == t["trigger_date"]:
                buy_idx = i
                break

        if buy_idx is None:
            continue

        # 检查是否过了60天
        days_held = 0
        current_price = closes[-1]
        for i in range(buy_idx + 1, len(closes)):
            days_held += 1
            if days_held >= 60:
                current_price = closes[i]
                break

        if days_held >= 60:
            # 到期结算
            ret = (current_price - t["buy_price"]) / t["buy_price"] * 100
            t["status"] = "settled"
            t["sell_price"] = current_price
            t["return_pct"] = round(ret, 2)
            t["days_held"] = days_held
            t["settle_date"] = datetime.now(CST).strftime("%Y-%m-%d")
            track["settled"].append(t)
            settled_count += 1

            match = "✅落在CI内" if 5.46 <= ret <= 10.12 else "⚠️低于CI" if ret < 5.46 else "✅高于CI"
            print(f"结算: {t['index_name']} {t['trigger_date']} 收益={ret:+.2f}% 预期+{t['expected_mean']}% {match}")
        else:
            # 更新当前浮盈
            if buy_idx < len(closes):
                cur_ret = (closes[-1] - t["buy_price"]) / t["buy_price"] * 100
                t["current_return"] = round(cur_ret, 2)
                t["days_held"] = days_held

    save_track(track)

    # 统计
    open_trades = [t for t in track["trades"] if t["status"] == "open"]
    settled = track["settled"]

    print(f"\n=== RSI策略前向验证状态 ===")
    print(f"  持仓中: {len(open_trades)}笔")
    for t in open_trades:
        cur = t.get("current_return", 0)
        days = t.get("days_held", 0)
        print(f"    {t['index_name']} {t['trigger_date']} RSI={t['trigger_rsi']} 第{days}天 浮盈{cur:+.1f}%")

    if settled:
        import numpy as np
        rets = [t["return_pct"] for t in settled]
        arr = np.array(rets)
        print(f"  已结算: {len(settled)}笔 mean={np.mean(arr):+.2f}% WR={np.mean(arr > 0) * 100:.0f}%")
        print(f"  回测预期: mean+7.82% WR92% 95%CI[+5.46%, +10.12%]")
        if np.mean(arr) >= 5.46:
            print(f"  → 实盘落在CI内 → edge延续 ✅")
        elif np.mean(arr) >= 0:
            print(f"  → 实盘低于CI但正收益 → edge衰减 ⚠️")
        else:
            print(f"  → 实盘为负 → edge失效 ❌")

    if new_triggers:
        print(f"\n  新触发: {new_triggers}笔")


if __name__ == "__main__":
    main()
