# -*- coding: utf-8 -*-
"""主入口 — main() + argparse + builders dict 调度。

从 feishu_daily_push.py 拆出。保持与原版完全一致的 CLI 接口和调度逻辑。
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone, timedelta

from .calendar import is_trading_day
from .cards import (
    build_premarket_card,
    build_intraday_card,
    build_postmarket_card,
    build_alert_card_live,
    build_scan_card,
    build_sentiment_card,
    build_test_card,
)
from .client import send_feishu

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))

# builders dict —— mode → card 构建函数
BUILDERS = {
    "premarket": build_premarket_card,
    "intraday": build_intraday_card,
    "postmarket": build_postmarket_card,
    "alert": build_alert_card_live,
    "scan": build_scan_card,
    "sentiment": build_sentiment_card,
    "test": build_test_card,
}


def main() -> None:
    """CLI 主入口。

    用法:
      python3 -m feishu.main --mode premarket
      python3 feishu_daily_push.py --mode test
    """
    parser = argparse.ArgumentParser(description="每日短线标的推送 → 飞书Bot")
    parser.add_argument(
        "--mode", required=True,
        choices=["premarket", "intraday", "postmarket", "alert", "scan", "sentiment", "test"],
    )
    parser.add_argument("--force", action="store_true", help="强制推送，跳过交易日判断")
    args = parser.parse_args()

    # 配置 logging（CLI 运行时）
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # test 模式不受交易日限制
    if args.mode != "test" and not args.force:
        now = datetime.now(CST)
        if not is_trading_day(now):
            date_str = now.strftime("%Y-%m-%d")
            weekday_name = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]
            print(f"⏭️ {date_str} {weekday_name}，非交易日，跳过推送（--force 可强制）")
            return

    builder = BUILDERS.get(args.mode)
    if builder is None:
        logger.error("未知 mode: %s", args.mode)
        sys.exit(1)

    card = builder()
    ok = send_feishu(card, mode=args.mode)
    if ok:
        print(f"✅ 推送成功 ({args.mode})", flush=True)
    else:
        print(f"❌ 推送失败 ({args.mode})", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
