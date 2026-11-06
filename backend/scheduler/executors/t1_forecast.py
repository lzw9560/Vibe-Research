# -*- coding: utf-8 -*-
"""S232 T+1 涨停预测 watchlist cron executors——15:10 生成 + 18:00 hit 回填。

观察池工具非交易信号。turn>20%+vr5>2 信号 lift 5.28x 真但 EV -0.87% 负。
"""
import json
import logging
from pathlib import Path
from typing import Any

from scheduler.cron_fire_audit import fire_receipt
from scheduler.executors.signals import _send_text_notification
from tools.t1_forecast import (
    backfill_t1_hit,
    generate_t1_watchlist,
    render_hit_report,
    render_watchlist_report,
)
from vr_paths import prev_trading_date_str, resolve_data_dir

_logger = logging.getLogger("vibe-research")

_FORECAST_DIR = Path(resolve_data_dir()) / "t1_forecast"


@fire_receipt("t1_watchlist_generate")
def t1_watchlist_generate(payload: dict[str, Any]) -> dict[str, Any]:
    """S232 T+1 涨停预测 watchlist——15:10 收盘后触发（T 日全量数据确认）。

    流程：
    1. generate_t1_watchlist(date)——筛 turn>20%+vr5>2 未涨停股作观察池
    2. render_watchlist_report——人话报告（含诚实标注：观察池非买入信号）
    3. 持久化 {date}_watchlist.json
    4. 飞书通知（观察池非交易信号，5.28x lift 真但 EV 负）

    Returns:
        {"status": "ok", "date": str, "edge_status": str, "count": int, "watchlist": dict}
    """
    target_date = payload.get("run_date") or prev_trading_date_str()
    _logger.info("[S232] t1_watchlist_generate start: date=%s", target_date)

    watchlist = generate_t1_watchlist(target_date)
    report_text = render_watchlist_report(watchlist)

    # 持久化
    try:
        _FORECAST_DIR.mkdir(parents=True, exist_ok=True)
        record_path = _FORECAST_DIR / f"{target_date}_watchlist.json"
        with open(record_path, "w", encoding="utf-8") as f:
            json.dump(watchlist, f, ensure_ascii=False, indent=2, default=str)
    except OSError as e:  # noqa: BLE001
        _logger.warning("[S232] watchlist 持久化失败: %s", e)
        record_path = None

    # 飞书通知（观察池非交易信号，P1砍2026-11-05：EV负默认关推送）
    if payload.get("notify", False):
        try:
            _send_text_notification(report_text)
            _logger.info("[S232] watchlist 飞书通知已发送: count=%d edge_status=%s",
                         watchlist.get("count"), watchlist.get("edge_status"))
        except Exception as e:  # noqa: BLE001
            _logger.warning("[S232] watchlist 飞书通知失败: %s", e)

    return {
        "status": "ok",
        "date": target_date,
        "edge_status": watchlist.get("edge_status"),
        "count": watchlist.get("count"),
        "watchlist": watchlist,
        "record_path": str(record_path) if record_path else None,
    }


@fire_receipt("t1_hit_backfill")
def t1_hit_backfill(payload: dict[str, Any]) -> dict[str, Any]:
    """S232 T+1 hit 回填——18:00 收盘后（zt_history 17:15 final 后）回填 T 日 watchlist 的 t1_zt。

    累积二次确认数据：T 日 watchlist 的 stocks 各自 T+1 是否涨停。
    命中率 vs 信号预期 4.34% 验证预测力（偏离 ±30% 标警）。

    Returns:
        {"status": "ok", "t_date": str, "t1_date": str, "total": int,
         "hit_count": int, "hit_rate": float, "expected_rate": float}
    """
    from vr_paths import last_trading_date_str
    t1_date = payload.get("t1_date") or last_trading_date_str()  # T+1 = 最近交易日（今天）
    t_date = payload.get("t_date") or prev_trading_date_str()  # T = 昨天
    _logger.info("[S232] t1_hit_backfill start: t_date=%s t1_date=%s", t_date, t1_date)

    result = backfill_t1_hit(t_date, t1_date)
    report_text = render_hit_report(result)

    # 飞书通知（命中率 vs 预期，P1砍2026-11-05：验证EV负观察池默认关推送）
    if payload.get("notify", False):
        try:
            _send_text_notification(report_text)
            _logger.info("[S232] hit_backfill 飞书通知已发送: hit_rate=%s",
                         result.get("hit_rate"))
        except Exception as e:  # noqa: BLE001
            _logger.warning("[S232] hit_backfill 飞书通知失败: %s", e)

    return {
        "status": "ok",
        **result,
        "report_text": report_text,
    }
