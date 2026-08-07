# -*- coding: utf-8 -*-
"""结算记录器（S034 R2）：settled 流转 → SettlementEngine 结算 → 写 winrate.db。

链路：workflow_state 行（entry_price/exit_price/strategy，用户 S033 表单自填）
→ SettlementEngine.settle()（return_pct/won/hold_days 纯计算）
→ WinRateRecord 写 winrate_records（喂既有胜率页 stats/trends/strategy 拆分）。

口径（spec D3，诚实近似）：系统不记录实际买入日——entry_date 用 trade_date
（候选日≈信号日），exit_date 用结算当天（北京时间）。

合规：结算数据全部来自用户自填价格 + 系统实际流转时间，客观记账无臆造；
胜率/收益属用户私有交易记录（winrate.db gitignored）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("vibe-research")

_BEIJING = timezone(timedelta(hours=8))


def _get_tracker():
    """winrate.db 写入器（测试注入点——绝不写用户真实库）。

    默认路径约定与 routers/win_rate.py 的模块级 _tracker 一致（data/winrate.db）。
    """
    from win_rate_tracker import WinRateTracker

    return WinRateTracker()


def settlement_summary(
    entry_price: Optional[float],
    exit_price: Optional[float],
    trade_date: str,
    settled_at: str,
) -> Dict[str, Any]:
    """结算摘要纯函数（recorder 与单股端点共享，防公式漂移）。

    return_pct 两位小数；entry 缺失/0 → 0.0。hold_days = settled 日 - trade_date（异常 → 0）。
    """
    if entry_price and exit_price is not None:
        return_pct = round(((exit_price - entry_price) / entry_price) * 100, 2)
    else:
        return_pct = 0.0
    try:
        hold_days = (
            datetime.strptime(settled_at[:10], "%Y-%m-%d").toordinal()
            - datetime.strptime(trade_date[:10], "%Y-%m-%d").toordinal()
        )
    except (TypeError, ValueError):
        hold_days = 0
    return {"return_pct": return_pct, "won": return_pct > 0, "hold_days": hold_days}


def _lookup_gene_score(code: str, trade_date: str) -> float:
    """基因 DB 回查当日 total_score；任何缺失/异常 → 0.0（score_breakdown low 桶，不臆造）。"""
    try:
        from limitup_screener.data import load_gene_scores

        genes = load_gene_scores(trade_date)
        for g in genes or []:
            if getattr(g, "code", None) == code:
                return float(getattr(g, "total_score", 0.0) or 0.0)
    except Exception as e:  # noqa: BLE001 — 回查是增强，失败兜底
        logger.debug("[settlement] gene_score 回查失败 %s %s: %s", code, trade_date, e)
    return 0.0


def record_settlement(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """结算一条 settled 状态行 → 写 winrate_records → 返摘要；价缺返 None。

    state 为 workflow_state 行 dict（含 entry_price/exit_price/strategy/trade_date 等）。
    """
    entry_price = state.get("entry_price")
    exit_price = state.get("exit_price")
    if entry_price is None or exit_price is None:
        return None

    from settlement.settlement_engine import SettlementEngine, SettlementInput

    settle_date = datetime.now(_BEIJING).strftime("%Y-%m-%d")
    trade_date = state.get("trade_date") or settle_date

    engine = SettlementEngine()  # 每次新建，无跨请求状态残留
    result = engine.settle(SettlementInput(
        code=state.get("code", ""),
        name=state.get("name", ""),
        strategy=state.get("strategy") or "",
        entry_price=float(entry_price),
        exit_price=float(exit_price),
        signal_date=trade_date,
        settle_date=settle_date,
    ))

    from win_rate_tracker import WinRateRecord

    record = WinRateRecord(
        stock_code=state.get("code", ""),
        stock_name=state.get("name", ""),
        strategy_used=state.get("strategy") or "",
        entry_date=trade_date,          # D3：候选日≈信号日（诚实近似）
        entry_price=float(entry_price),
        exit_date=settle_date,
        exit_price=float(exit_price),
        return_pct=round(result.return_pct, 2),
        is_win=result.won,
        gene_score=_lookup_gene_score(state.get("code", ""), trade_date),
        sti_label="",                    # 无数据源，留空（列可空）
        sector="",
    )
    _get_tracker().add_record(record)

    return settlement_summary(float(entry_price), float(exit_price), trade_date, result.date)
