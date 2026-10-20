#!/usr/bin/env python3
"""MACD金叉自动监控——每天检查MACD是否金叉+推送飞书。

RSI<30已触发，等MACD金叉确认：
- 金叉后三因子全部触发（RSI<30+MACD金叉+空头排列）mean+13.65% WR100%
- 预估7个交易日后金叉

跑法：python3 scripts/macd_cross_monitor.py
"""
import json, os, sys, subprocess, time
import numpy as np
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

CST = timezone(timedelta(hours=8))
HITHINK = "/Users/lizhiwei/.nvm/versions/node/v24.21.0/bin/hithink-finance"


def load_env():
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if webhook: return webhook
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if "FEISHU_WEBHOOK_URL=" in line:
                    return line.split("=", 1)[1].strip().strip('"')
    return ""


def send_feishu(text, urgency="normal"):
    webhook = load_env()
    if not webhook: return False
    import urllib.request
    template = "red" if urgency == "critical" else "orange" if urgency == "urgent" else "blue"
    card = {
        "header": {
            "title": {"tag": "plain_text", "content": f"📊 MACD金叉监控 | {datetime.now(CST).strftime('%H:%M')}"},
            "template": template,
        },
        "elements": [{"tag": "markdown", "content": text}],
    }
    payload = json.dumps({"msg_type": "interactive", "card": card}).encode("utf-8")
    req = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read()).get("code") == 0
    except:
        return False


def calc_ema(data, period):
    ema = [data[0]]
    k = 2 / (period + 1)
    for i in range(1, len(data)):
        ema.append(data[i] * k + ema[-1] * (1 - k))
    return ema


def calc_rsi(closes):
    if len(closes) < 15: return 50
    changes = [closes[j] - closes[j-1] for j in range(len(closes)-14, len(closes))]
    gains = [c for c in changes if c > 0]
    losses = [-c for c in changes if c < 0]
    return 100 - 100 / (1 + (np.mean(gains) if gains else 0) / (np.mean(losses) if losses else 0.001))


def main():
    now = datetime.now(CST)
    if now.weekday() >= 5:
        return  # 周末跳过

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - 60 * 86400000

    r = subprocess.run(
        [HITHINK, "index", "history", "--thscode", "000001.SH",
         "--start-ms", str(start_ms), "--end-ms", str(end_ms)],
        capture_output=True, text=True, timeout=15,
    )
    try:
        d = json.loads(r.stdout)
        items = d.get("data", {}).get("item", [])
        closes = [i["close_price"] for i in items if i.get("close_price")]
        if len(closes) < 30:
            print("数据不足")
            return
    except:
        print("数据拉取失败")
        return

    # RSI
    rsi = calc_rsi(closes)

    # MACD
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    dif = [ema12[i] - ema26[i] for i in range(len(closes))]
    dea = calc_ema(dif, 9)

    cur_dif = dif[-1]
    cur_dea = dea[-1]
    is_golden = cur_dif > cur_dea

    # 检查今天是否刚金叉
    just_crossed = False
    if len(dif) >= 2 and dif[-1] > dea[-1] and dif[-2] <= dea[-2]:
        just_crossed = True

    # MACD收敛
    converging = abs(dif[-1] - dea[-1]) < abs(dif[-2] - dea[-2]) if len(dif) >= 2 else False

    # 预估金叉天数
    days_to_cross = None
    if not is_golden:
        diffs = [abs(dif[i] - dea[i]) for i in range(max(0, len(dif) - 10), len(dif))]
        if len(diffs) >= 2:
            shrinks = [diffs[i] - diffs[i+1] for i in range(len(diffs) - 1) if diffs[i+1] < diffs[i]]
            if shrinks and np.mean(shrinks) > 0:
                days_to_cross = int(abs(cur_dif - cur_dea) / np.mean(shrinks))

    # 均线排列
    ma5 = np.mean(closes[-5:])
    ma10 = np.mean(closes[-10:])
    ma20 = np.mean(closes[-20:])
    is_bear = closes[-1] < ma5 < ma10 < ma20

    now_str = now.strftime("%Y-%m-%d %H:%M")

    if just_crossed and rsi < 30:
        # 三因子全部触发！
        text = f"**🚨🚨🚨 MACD金叉确认——三因子全部触发！**\n\n"
        text += f"时间: {now_str}\n"
        text += f"上证: {closes[-1]:.0f}\n"
        text += f"RSI: {rsi:.0f} ✅\n"
        text += f"MACD: DIF={cur_dif:.1f} DEA={cur_dea:.1f} ✅刚金叉\n"
        text += f"空头排列: {'✅' if is_bear else '❌'}\n\n"
        text += f"**三因子全部触发——最强买入信号**\n"
        text += f"历史: mean+13.65% WR100% p=0.0048\n"
        text += f"操作: 买上证50ETF(510050) 100%仓位\n"
        text += f"止盈: +30% 持有: 最长20天 不止损\n"
        send_feishu(text, "critical")
        print(f"{now_str} 🚨三因子全部触发！已推送")
    elif is_golden and rsi < 30:
        text = f"**🚨 MACD已金叉+RSI<30——买入信号**\n"
        text += f"RSI={rsi:.0f} ✅ MACD金叉 ✅\n"
        text += f"预期: +9.53% WR100%（RSI+MACD金叉历史）\n"
        send_feishu(text, "urgent")
        print(f"{now_str} RSI+MACD金叉已触发")
    elif rsi < 30 and not is_golden:
        text = f"**⏳ RSI已触发 MACD未金叉——等待确认**\n"
        text += f"RSI={rsi:.0f} ✅ MACD死叉(DIF={cur_dif:.1f} DEA={cur_dea:.1f}) ❌\n"
        text += f"收敛: {'✅' if converging else '❌'}\n"
        if days_to_cross:
            text += f"预估金叉: ~{days_to_cross}个交易日后\n"
        text += f"\n激进: 现在买（RSI={rsi:.0f}极端超卖 预期+7.82% WR92%）\n"
        text += f"稳健: 等金叉（WR100% mean+9.53%）\n"
        send_feishu(text)
        print(f"{now_str} RSI触发但MACD未金叉 预估{days_to_cross}天后金叉")
    else:
        print(f"{now_str} 无信号 RSI={rsi:.0f}")


if __name__ == "__main__":
    main()
