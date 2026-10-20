#!/usr/bin/env python3
"""RSI择时自动监控——每天定时检测4个指数RSI+推送飞书。

回测验证：
- RSI<30买入持20天: 上证mean+3.62% WR81% p=0.0002
- RSI<25买入持20天: 创业板mean+6.24% WR93% p=0.0001
- 48个参数组合全部统计显著

定时：每日08:25盘前推送（交易日）
跑法：python3 scripts/rsi_monitor.py
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from strategies.rsi_timing import calculate_rsi, check_rsi_signal, RSI_PARAMS

CST = timezone(timedelta(hours=8))
HITHINK = "/Users/lizhiwei/.nvm/versions/node/v24.21.0/bin/hithink-finance"

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


def send_feishu(card):
    import urllib.request
    webhook = load_env()
    if not webhook:
        print("无FEISHU_WEBHOOK_URL")
        return False
    payload = json.dumps({"msg_type": "interactive", "card": card}).encode("utf-8")
    req = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            return result.get("code") == 0
    except Exception as e:
        print(f"发送失败: {e}")
        return False


def main():
    now = datetime.now(CST)
    if now.weekday() >= 5:  # 周末跳过
        print(f"周末跳过: {now.strftime('%Y-%m-%d %A')}")
        return

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - 60 * 86400000

    signals = []
    for code, params in RSI_PARAMS["indices"].items():
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
            sig = check_rsi_signal(code, closes)
            signals.append(sig)
        except Exception:
            continue

    any_triggered = any(s.is_triggered for s in signals)
    now_str = now.strftime("%Y-%m-%d %H:%M")

    if not any_triggered:
        print(f"{now_str} 无RSI信号触发")
        return

    # 构建飞书卡片
    card = {
        "header": {
            "title": {"tag": "plain_text", "content": f"🚨 RSI择时信号 | {now_str}"},
            "template": "red",
        },
        "elements": [
            {"tag": "markdown", "content": f"**【RSI信号触发 {now_str}】**\n\n"},
        ],
    }

    text = ""
    for sig in signals:
        emoji = "✅" if sig.is_triggered else "❌"
        text += f"{emoji} {sig.index_name} RSI={sig.current_rsi} 阈值<{sig.threshold}\n"
        if sig.is_triggered:
            text += f"  历史: n={sig.sample_size} mean+{sig.expected_return}% WR{sig.win_rate}% p={sig.p_value}\n"
            text += f"  操作: 买ETF持{sig.hold_days}天 止损{sig.stop_loss_pct:.0%}\n"

    text += "\n**策略回测**\n"
    text += "• RSI<30: 48组参数全显著(p<0.05)\n"
    text += "• 最优: 不止盈不止损持60天 mean+7.82% WR92%\n"
    text += "• 实战: 止盈5%持20天 mean+2.74% WR85%\n"
    text += "• RSI<20历史100%胜率\n"

    card["elements"][0]["content"] += text

    card["elements"].append({
        "tag": "note",
        "content": "⚠️ 统计显著不等于100%稳赚。不构成投资建议。",
    })

    success = send_feishu(card)
    print(f"{now_str} RSI信号推送: {'✅成功' if success else '❌失败'}")


if __name__ == "__main__":
    main()
