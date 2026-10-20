#!/usr/bin/env python3
"""持仓+RSI联动监控——每天自动检查止损/减仓/RSI退出信号+推送飞书。

检查项：
1. 持仓4只是否触及止损线（支撑位-3%）
2. 上证是否站上3848(MA20)→减仓信号
3. 上证是否跌破3707→清仓信号
4. RSI是否>60→RSI策略退出
5. RSI是否<30→买入信号

跑法：python3 scripts/position_rsi_monitor.py
"""
import json
import os
import sys
import subprocess
import time
import urllib.request
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from strategies.rsi_timing import calculate_rsi, RSI_PARAMS

CST = timezone(timedelta(hours=8))
HITHINK = "/Users/lizhiwei/.nvm/versions/node/v24.21.0/bin/hithink-finance"
API = "http://127.0.0.1:8900"

# 持仓止损线（支撑位×0.97）
STOP_LOSS = {
    "002156": 46.61,  # 通富微电 48.05×0.97
    "002185": 13.52,  # 华天科技 13.94×0.97
    "002281": 127.85, # 光迅科技 131.80×0.97
    "600584": 53.97,  # 长电科技 55.64×0.97
}

MA20_SIGNAL = 3848   # 减仓信号
CLEAR_SIGNAL = 3707  # 清仓信号
RSI_EXIT = 60         # RSI退出
RSI_BUY = 30          # RSI买入


def load_env():
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if webhook:
        return webhook
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if "FEISHU_WEBHOOK_URL=" in line:
                    return line.split("=", 1)[1].strip().strip('"')
    return ""


def send_feishu(text, urgency="normal"):
    webhook = load_env()
    if not webhook:
        return False
    template = "red" if urgency == "critical" else "orange" if urgency == "urgent" else "blue"
    card = {
        "header": {
            "title": {"tag": "plain_text", "content": f"📊 持仓+RSI监控 | {datetime.now(CST).strftime('%H:%M')}"},
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


def main():
    now = datetime.now(CST)
    if now.weekday() >= 5:
        return  # 周末跳过

    alerts = []
    urgency = "normal"

    # 1. 持仓止损检查
    try:
        with urllib.request.urlopen(f"{API}/api/portfolio", timeout=5) as r:
            portfolio = json.loads(r.read())["data"]
        
        for h in portfolio["holdings"]:
            code = h["code"]
            price = h["price"]
            stop = STOP_LOSS.get(code, 0)
            if stop > 0 and price <= stop:
                alerts.append(f"🔴 {h['name']}({code}) 现价{price} ≤ 止损线{stop} → 清仓该只")
                urgency = "critical"
            elif stop > 0:
                gap = (price - stop) / stop * 100
                if gap < 5:
                    alerts.append(f"⚠️ {h['name']}({code}) 现价{price} 距止损{stop}仅{gap:+.1f}%")
                    if urgency == "normal":
                        urgency = "urgent"
    except:
        alerts.append("⚠️ 持仓API不可用")

    # 2. 上证RSI+均线检查
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
        if len(closes) >= 20:
            cur = closes[-1]
            ma20 = sum(closes[-20:]) / 20
            rsi = calculate_rsi(closes)

            # 减仓信号
            if cur >= MA20_SIGNAL:
                alerts.append(f"🟢 上证{cur:.0f}站上MA20({MA20_SIGNAL}) → 减仓1/3(光迅优先)")
                urgency = "urgent"
            elif cur >= ma20:
                alerts.append(f"🟡 上证{cur:.0f}接近MA20({ma20:.0f}) 距{(cur-ma20)/ma20*100:+.1f}%")

            # 清仓信号
            if cur <= CLEAR_SIGNAL:
                alerts.append(f"🔴 上证{cur:.0f}跌破年内最低{CLEAR_SIGNAL} → 全部清仓")
                urgency = "critical"
            else:
                gap = (cur - CLEAR_SIGNAL) / CLEAR_SIGNAL * 100
                if gap < 2:
                    alerts.append(f"⚠️ 上证{cur:.0f}距年内最低{CLEAR_SIGNAL}仅{gap:+.1f}%")
                    if urgency == "normal":
                        urgency = "urgent"

            # RSI信号
            if rsi >= RSI_EXIT:
                alerts.append(f"🔴 上证RSI={rsi:.0f}>{RSI_EXIT} → RSI策略退出(卖出)")
                urgency = "urgent"
            elif rsi < RSI_BUY:
                alerts.append(f"✅ 上证RSI={rsi:.0f}<{RSI_BUY} → 买入信号(持有中)")
            else:
                alerts.append(f"⚪ 上证RSI={rsi:.0f} 中性区间({RSI_BUY}~{RSI_EXIT})")
    except:
        alerts.append("⚠️ 上证数据拉取失败")


    # MACD收敛+金叉预估
    try:
        def calc_ema(data, period):
            ema = [data[0]]
            k = 2/(period+1)
            for i in range(1, len(data)):
                ema.append(data[i]*k + ema[-1]*(1-k))
            return ema
        
        ema12 = calc_ema(closes, 12)
        ema26 = calc_ema(closes, 26)
        dif = [ema12[i]-ema26[i] for i in range(len(closes))]
        dea = calc_ema(dif, 9)
        
        cur_dif = dif[-1]
        cur_dea = dea[-1]
        macd_converging = abs(dif[-1]-dea[-1]) < abs(dif[-2]-dea[-2]) if len(dif)>=2 else False
        
        # 预估金叉天数
        days_to_cross = None
        if cur_dif < cur_dea:
            diffs = [abs(dif[i]-dea[i]) for i in range(max(0,len(dif)-10), len(dif))]
            if len(diffs) >= 2:
                shrinks = [diffs[i]-diffs[i+1] for i in range(len(diffs)-1) if diffs[i+1] < diffs[i]]
                if shrinks and np.mean(shrinks) > 0:
                    days_to_cross = int(abs(cur_dif-cur_dea) / np.mean(shrinks))
        
        macd_text = f"\n**MACD状态**\n"
        macd_text += f"DIF={cur_dif:.1f} DEA={cur_dea:.1f} {'✅金叉' if cur_dif>cur_dea else '❌死叉'}\n"
        macd_text += f"收敛: {'✅DIF向DEA靠拢' if macd_converging else '❌发散'}\n"
        if days_to_cross is not None:
            macd_text += f"预估金叉: ~{days_to_cross}个交易日后\n"
            macd_text += f"→ 金叉后三因子全部触发(WR100% mean+13.65%)\n"
        alerts.append(macd_text.strip())
    except Exception as e:
        pass

    # 3. 推送
    if alerts:
        text = "\n".join(alerts)
        text += f"\n\n关键价位: 减仓{MA20_SIGNAL} 清仓{CLEAR_SIGNAL} RSI退出>{RSI_EXIT}"
        success = send_feishu(text, urgency)
        print(f"[{now.strftime('%H:%M')}] {urgency}: {len(alerts)}条信号 推送={'✅' if success else '❌'}")
        for a in alerts:
            print(f"  {a}")
    else:
        print(f"[{now.strftime('%H:%M')}] 无信号")


if __name__ == "__main__":
    main()
