#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日短线标的推送 → 飞书Bot（薄 wrapper，向后兼容）。

⚠️ 本文件已重构为 feishu/ 包的入口 wrapper（exp-1 审计 god script 拆分）。
实际逻辑在 feishu/ 包：
  feishu/client.py      send_feishu + ping_healthchecks + tenacity 重试
  feishu/calendar.py    is_trading_day + load_trade_calendar
  feishu/data.py        run_cli + 各数据获取函数
  feishu/scanners.py    scan_strategy4_tail_drop（策略1窒息量已证伪删除）
  feishu/sentiment.py   calculate_sentiment_score
  feishu/cards.py       所有 build_*_card
  feishu/main.py        main() + argparse + 调度

用法不变（CLI 接口完全一致）:
  # 盘前推送（8:30）：昨日复盘 + 今日候选
  python3 feishu_daily_push.py --mode premarket

  # 尾盘扫描（14:30）：策略4尾盘错杀信号
  python3 feishu_daily_push.py --mode intraday

  # 盘后复盘（15:30）：今日龙虎榜+热股榜+明日候选
  python3 feishu_daily_push.py --mode postmarket

  # 手动测试
  python3 feishu_daily_push.py --mode test

依赖: hithink-finance CLI + 飞书Webhook
配置: 从 .env 读取 FEISHU_WEBHOOK_URL

向后兼容：本 wrapper 保持 `python3 feishu_daily_push.py --mode X` 入口不变，
定时任务 plist 无需修改。
"""
from feishu.main import main

if __name__ == "__main__":
    main()
