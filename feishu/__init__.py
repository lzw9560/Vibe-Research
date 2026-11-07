"""feishu — 每日短线标的推送 → 飞书Bot（拆分自 feishu_daily_push.py god script）。

模块职责：
- client.py:      send_feishu + ping_healthchecks + tenacity 重试
- calendar.py:    is_trading_day + load_trade_calendar + _KNOWN_HOLIDAYS
- data.py:        run_cli + 各数据获取函数（指数/热股/龙虎榜/连板/飙升/全市场快照）
- scanners.py:    scan_strategy4_tail_drop（策略1窒息量已证伪删除）
- sentiment.py:   calculate_sentiment_score（纯函数，最易测）
- cards.py:       所有 build_*_card 卡片构建
- main.py:        main() + argparse + builders dict 调度

向后兼容：feishu_daily_push.py 改为 `from feishu.main import main; main()` 薄 wrapper。
"""
