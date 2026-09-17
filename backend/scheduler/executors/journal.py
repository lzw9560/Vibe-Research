# -*- coding: utf-8 -*-
"""S175 R2 — journal executors：模拟盘闭环盘后跑（THE orchestrator 主线，BREAK-0 fix）。

journal_recorder.run_daily 已是完整顺序管线（C1 orchestrator 非订阅，DI 注入
journal/executor/bars_provider），但未接 scheduler 31 dispatch / seed cron——生产
不跑 → trade_journal.db 空 → 所有下游验证/推荐/跟单 vacuous。本 executor 接
call-point wiring 点火（S175 P0 最关键）。

执行序（盘后 16:45，晚 kline_refresh 16:30）：
  1. settle_pending_breakout()——重算昨日未平 'hold'（path_return T+1 guard 需 T+2+ bars）
  2. run_daily(target_date=prev, arms=['floor','breakout'])——floor MTM + breakout path_return
  3. update_floor_mtm()——floor 每日 MTM 更新

依赖：kline_refresh 16:30 已刷 baostock_kline_cache.json（A股 bars）；
ETF bars 走 fetch_etf_hist（akshare push2delay，非 cache）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("vibe-research")


def trade_journal_daily(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S175 R2 — 盘后 16:45 跑 journal_recorder 闭环。

    payload 可选 target_date（YYYY-MM-DD）覆盖默认 prev_trading_date_str（T-1 信号日，
    T1OpenFill 在 T 成交，C5 fix no_t1_bar 误标 unbuyable）。

    返 {settled_pending, arms, floor_mtm}——executor 末尾 Phase 1 调 PaperPortfolio.equity()
    + drawdown_breaker.compute_drawdown()（从 API 层移生产）另在 P1 接。
    """
    from strategies.journal_recorder import JournalRecorder  # noqa: PLC0415
    from engine.bars_provider import KlineCacheBarsProvider  # noqa: PLC0415

    bars_provider = KlineCacheBarsProvider()
    recorder = JournalRecorder(bars_provider=bars_provider)

    target_date = payload.get("target_date")  # None → run_daily default prev_trading_date_str
    settled = recorder.settle_pending_breakout()
    # S211（2026-09-17）：arms 加 consecutive_relay——唯一已证 edge（bull +1.055%
    # drift-adjusted）arm 从 dormant 转活。scan_consecutive_relay 直读 zt_history.db
    # （17:15 zt_history_snapshot 已写当日涨停池，早于 17:30 trade_journal_daily）。
    # regime cap bite：bull ×0.5 provisional（综合 refuted 保守，待 60 天 forward OOS 升 ×1.0）。
    results = recorder.run_daily(target_date=target_date, arms=["floor", "breakout", "trend", "consecutive_relay"])
    mtm = recorder.update_floor_mtm(target_date=target_date)
    # S175 R10/R11：PaperPortfolio.equity() 落盘供 R9 推荐 sizing（R9↔R10 接线 SH1 fix）+
    # drawdown_breaker 接生产路径（从 API 层移 executor，overlay stub deferred）。
    # PaperPortfolio() 默认 DB = recorder 同一 trade_journal.db（resolve_data_dir）。
    from engine.paper_portfolio import PaperPortfolio  # noqa: PLC0415
    pp = PaperPortfolio()
    equity = pp.equity()
    drawdown_status = pp.drawdown_status()
    logger.info(
        "trade_journal_daily done: settled=%s arms=%s floor_mtm=%s equity=%s",
        settled, results, mtm, equity,
    )
    return {
        "settled_pending": settled, "arms": results, "floor_mtm": mtm,
        "equity": equity, "drawdown_status": drawdown_status,
    }


def loss_breaker_enforce(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S203 T6 — 吃大面 enforce gate 盘后跑。

    读 journal 持仓浮亏 → 算 per-code block_add（单笔>5%）/ block_new（合计>8%）+冷却。
    ⛔ 不碰 final_size sizing——只算+返 enforce 状态。生产 sizing 是否复合此
    intraday_mult 由用户 review 决定（T6 只接 gate，memory 标涉生产仓位）。
    """
    from risk_rules import loss_breaker_enforce as _enforce
    try:
        result = _enforce()
        return {
            "status": "ok",
            "is_blocked_new": result["is_blocked_new"],
            "n_codes": result["n_codes"],
            "n_open": result["n_open"],
            "total_account_loss_pct": result["total_account_loss_pct"],
            "cooldown_until": result["cooldown_until"],
            "date": result["date"],
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("[loss_breaker_enforce] failed: %s", repr(e)[:200])
        return {"status": "error", "error": repr(e)[:200]}
