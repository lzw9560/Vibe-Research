# -*- coding: utf-8 -*-
"""S166 — 交易日志 + 个人风控路由（journal 7 + risk 9 端点，共 16）。

与既有 routers/risk.py（S055/S126 市场级风险 dashboard/seats/bomb-alerts/seal-snapshots）
路径无碰撞（不同子路径），分文件命名空间隔离——两者共存，勿覆盖 routers/risk.py。

⛔ 所有端点返个人交易数据——**不接入 AI prompt**（守 AGENTS.md 个人数据隔离：本路由不 import
chat/ai.tools；journal/at_risk/risk_rules/excursion/attribution/inbox 均为个人数据只读 API 给前端
渲染，AI 永远看不到）。

S166 fresh-impl（design-agnostic）。路由结构参考自 cb54a96 历史，非整文件复活。
"""
from __future__ import annotations

from typing import Any, Dict

import asyncio
import json
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import journal
import at_risk
import risk_rules
import excursion
import attribution
import inbox

# S173: 闭环 ledger（trade_journal）+ drawdown 熔断——惰性 import 避循环依赖
from engine.trade_journal import TradeJournal
from engine.drawdown_breaker import DrawdownBreaker
from vr_paths import resolve_data_dir

router = APIRouter(tags=["journal"])


# ───────────────────────── closed-loop ledger 2 端点（S173） ────────────────
@router.get("/api/journal/closed-loop")
async def journal_closed_loop(limit: int = Query(500, ge=1, le=5000)) -> Dict[str, Any]:
    """闭环 ledger：跨臂 trade_journal 记录 + 聚合统计（winrate/Sharpe/coverage_rate）。

    S173 闭环账本（模拟/纸面臂胜率闭环），与 journal/list（手动真实成交）分离。
    后端未就绪 → 各 section 如实呈现空/available:False（不臆造 mock 交易）。
    """
    def _build() -> dict:
        tj = TradeJournal()
        records = tj.query_records(is_dead_arm=None, limit=limit)
        aggregate = tj.aggregate_by_arm()
        return {
            "available": True,
            "records": [
                {
                    "signal_id": r.signal_id, "arm": r.arm,
                    "stock_code": r.stock_code,
                    "entry_price": r.entry_price, "entry_date": r.entry_date,
                    "exit_price": r.exit_price, "exit_date": r.exit_date,
                    "exit_reason": r.exit_reason,
                    "net_pnl": r.net_pnl, "pnl_unit": r.pnl_unit,
                    "cost_pct": r.cost_pct, "gross_return": r.gross_return,
                    "is_realized": r.is_realized,
                    "unrealized_pnl": r.unrealized_pnl,
                    "is_dead_arm": r.is_dead_arm,
                }
                for r in records
            ],
            "aggregate": aggregate,
        }
    return await asyncio.to_thread(_build)


@router.get("/api/journal/winrate-trends")
async def journal_winrate_trends(arm: str | None = Query(None)) -> Dict[str, Any]:
    """S183：累积胜率时序曲线——按周分桶实时聚合 + Wilson 95% CI + 双轴诚实标签。

    数据源 trade_journal（is_realized=1 AND is_dead_arm=0 AND net_pnl 非 None 非 0）。
    空表返 {available:True, trends:[]}，前端显空态占位（需 ≥30 真实成交才有统计意义）。
    不接入 AI prompt（守个人数据隔离，同 closed-loop）。
    """
    def _build() -> dict:
        tj = TradeJournal()
        trends = tj.query_winrate_trends(arm=arm)
        return {"available": True, "trends": trends}
    return await asyncio.to_thread(_build)


@router.get("/api/journal/arm-forward-monitor")
async def journal_arm_forward_monitor(arm: str = Query("consecutive_relay")) -> Dict[str, Any]:
    """consecutive_relay arm forward OOS 监控——backtest baseline 对比 + 距 60 天倒计时 + kill criteria 评估（报告不 enforce）。

    arm 已通电生产（50 股/笔 ×0.5 provisional），无 arm 级 kill switch——此 endpoint 报告
    forward 指标供人工监控。enforce（auto-pause）defer 到 60 天数据后（YAGNI：数据少时
    enforce 过早，4 专家共识先报告型）。

    数据源 trade_journal（is_realized=1 AND is_dead_arm=0）+ aggregate_by_arm stats。
    kill criteria 复用 forward_test 逻辑（consecutive_loss<8 / winrate>=60 / lift>=2.0）
    但在 trade_journal records 上算，不建 arm_status 表（YAGNI 15 行不改 schema）。
    """
    def _build() -> dict:
        tj = TradeJournal()
        stats = tj.aggregate_by_arm(arm=arm).get(arm, {})
        records = tj.query_records(arm=arm, is_realized=1, is_dead_arm=0, limit=5000)
        # consecutive_loss：从最近往前数连亏（复用 forward_test kill criteria 逻辑）
        consecutive_loss = 0
        for r in sorted(records, key=lambda x: x.entry_date or "", reverse=True):
            if r.net_pnl is not None and r.net_pnl < 0:
                consecutive_loss += 1
            else:
                break
        n_days = stats.get("n_days") or stats.get("days") or 0
        n_picks = stats.get("n_picks") or stats.get("n") or len(records)
        forward_mean = stats.get("net_mean_pct") or stats.get("mean_net_pct")
        baseline = 1.055  # consecutive_relay bull backtest drift-adjusted（对比基准）
        winrate = stats.get("net_winrate") or stats.get("winrate") or 0
        return {
            "available": True,
            "arm": arm,
            "n_picks": n_picks,
            "n_days": n_days,
            "days_to_60": max(0, 60 - n_days),
            "status": "underpowered" if n_days < 60 else "ready_for_verdict",
            "forward": {
                "net_mean_pct": forward_mean,
                "winrate": winrate,
                "consecutive_loss": consecutive_loss,
                "baseline_backtest_pct": baseline,
                "vs_baseline": (forward_mean - baseline) if forward_mean is not None else None,
            },
            "kill_criteria": {
                "consecutive_loss_ge_5": consecutive_loss >= 5,  # Tier 1 auto-pause 候选（报告）
                "winrate_lt_50": winrate < 50,
                "days_lt_60": n_days < 60,
            },
            "stats_full": stats,
            "note": "报告型 monitor（不 enforce）。enforce defer 到 60 天数据后。"
                    "kill criteria 复用 forward_test（consecutive_loss<8/winrate>=60/lift>=2.0）。",
        }
    return await asyncio.to_thread(_build)


@router.get("/api/journal/drawdown-status")
async def journal_drawdown_status() -> Dict[str, Any]:
    """drawdown 熔断状态：per-arm + portfolio equity/回撤/size_multiplier。"""
    def _build() -> dict:
        breaker = DrawdownBreaker()
        return breaker.full_status()
    return await asyncio.to_thread(_build)


# ───────────────────────────────── journal 7 端点 ─────────────────────────


# ───────────────────────── journal 7 端点 ─────────────────────────
@router.get("/api/journal/list")
async def journal_list(limit: int = Query(200, ge=1, le=5000)) -> Dict[str, Any]:
    """交易日志列表（倒序，截断 limit；持仓聚合须走 all_trades 不截断）。"""
    return await asyncio.to_thread(journal.list_trades, limit)


@router.get("/api/journal/stats")
async def journal_stats() -> Dict[str, Any]:
    """自我体检：按情绪/打法/计划/板别/持有 分组的历史表现统计。"""
    return await asyncio.to_thread(journal.stats)


class AddTradeBody(BaseModel):
    date: str
    code: str
    name: str = ""
    playbook: str
    pnl_pct: float | None = None
    as_planned: bool | None = None
    note: str = ""
    fills: list[dict] | None = None
    planned_stop: float | None = None
    planned_target: float | None = None


@router.post("/api/journal/add")
async def journal_add(body: AddTradeBody) -> Dict[str, Any]:
    """记一笔交易（自动钉上当时市场环境快照）。"""
    try:
        return await asyncio.to_thread(
            journal.add_trade, body.date, body.code, body.name, body.playbook,
            body.pnl_pct, body.as_planned, body.note, body.fills,
            body.planned_stop, body.planned_target)
    except ValueError as e:
        raise HTTPException(400, f"参数错误：{e}") from e
    except RuntimeError as e:
        raise HTTPException(500, f"写入失败：{e}") from e


class UpdateTradeBody(BaseModel):
    fills: list[dict] | None = None
    note: str | None = None
    as_planned: bool | None = None
    planned_stop: float | None = None
    planned_target: float | None = None


@router.post("/api/journal/update")
async def journal_update(
    trade_id: str = Query(..., description="交易 ID"),
    body: UpdateTradeBody | None = None,
) -> Dict[str, Any]:
    """更新一笔交易（补卖出/改计划边界留痕 planned_edited_at）。

    用 model_fields_set 区分「字段未传」(保持原值 _UNSET) vs 「显式传 null」(清空)——
    Pydantic 二者都反序列化为 None，旧写法把 null 当未传 → as_planned/planned_stop/
    planned_target 无法经 API 清空。
    """
    body = body or UpdateTradeBody()
    fs = body.model_fields_set          # Pydantic v2：显式提供的字段集
    unset = journal._UNSET
    # 显式提供（含 null=清空）→ 传值；未传 → _UNSET（保持原值）
    def _opt(field: str, default):
        return getattr(body, field) if field in fs else default
    try:
        return await asyncio.to_thread(
            journal.update_trade, trade_id,
            fills=_opt("fills", None),
            note=_opt("note", None),
            as_planned=_opt("as_planned", unset),
            planned_stop=_opt("planned_stop", unset),
            planned_target=_opt("planned_target", unset),
        )
    except ValueError as e:
        raise HTTPException(400, f"参数错误：{e}") from e


@router.post("/api/journal/delete")
async def journal_delete(trade_id: str = Query(..., description="交易 ID")) -> Dict[str, Any]:
    """删除一笔交易。"""
    return await asyncio.to_thread(journal.delete_trade, trade_id)


@router.get("/api/journal/fees")
async def journal_fees() -> Dict[str, Any]:
    """费率配置（commission/stamp_tax/transfer_fee；is_default 标是否初值）。"""
    return await asyncio.to_thread(journal.load_fees)


class SaveFeesBody(BaseModel):
    commission_rate: float | None = None
    commission_min: float | None = None
    stamp_tax_rate: float | None = None
    transfer_fee_rate: float | None = None


@router.post("/api/journal/fees")
async def journal_save_fees(body: SaveFeesBody) -> Dict[str, Any]:
    """保存费率（只收已知字段，负数/非数字拒绝；未传字段用默认值兜底）。"""
    try:
        return await asyncio.to_thread(journal.save_fees, body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, f"参数错误：{e}") from e


# ───────────────────────── risk 9 端点（个人交易风控）─────────────────────────
@router.get("/api/risk/report")
async def risk_report() -> Dict[str, Any]:
    """个人风控总报告：权益曲线 + 纪律归因 + 规则违反。"""
    return await asyncio.to_thread(risk_rules.report)


@router.get("/api/risk/at-risk")
async def risk_at_risk() -> Dict[str, Any]:
    """在险资金：当前持仓最坏情况亏多少（bounded 合计 + unbounded 单独报 + R3 诚实标签）。"""
    return await asyncio.to_thread(at_risk.report)


@router.get("/api/risk/excursion")
async def risk_excursion(limit: int = Query(300, ge=1, le=5000)) -> Dict[str, Any]:
    """MFE/MAE 汇总（逐笔拉行情，单独端点不进 report——首次慢）。"""
    return await asyncio.to_thread(excursion.summary, limit)


@router.get("/api/risk/attribution")
async def risk_attribution(limit: int = Query(500, ge=1, le=5000)) -> Dict[str, Any]:
    """判断/执行归因四格（⚠️ 暂无 reflection 数据→降级 available:False，不臆造命中）。"""
    return await asyncio.to_thread(attribution.attribution, limit)


@router.get("/api/risk/inbox")
async def risk_inbox(limit: int = Query(500, ge=1, le=5000)) -> Dict[str, Any]:
    """异常交易收件箱（按自设阈值 + 自中位偏离筛，不排严重程度）。"""
    return await asyncio.to_thread(inbox.build, limit)


@router.get("/api/risk/rules")
async def risk_rules_get() -> Dict[str, Any]:
    """风险宪法（用户自设阈值；is_default 标是否初值）。

    ⚠️ load_rules() 内部用 `_is_default`（下划线=私有标记），API 对外统一 `is_default`
    （与 at_risk.report / inbox.build 一致），否则前端契约读 is_default 永远 undefined
    → "还在用初值" 警告永不渲染（frontend review contract-mismatch HIGH finding）。
    """
    rules = await asyncio.to_thread(risk_rules.load_rules)
    return {k: v for k, v in rules.items() if k != "_is_default"} | {
        "is_default": bool(rules.get("_is_default", False)),
    }


class SaveRulesBody(BaseModel):
    max_loss_per_trade_pct: float | None = None
    max_loss_per_day_pct: float | None = None
    max_positions: int | None = None
    max_trades_per_day: int | None = None
    pause_after_losses: int | None = None
    max_unplanned_ratio: float | None = None


@router.post("/api/risk/rules")
async def risk_rules_save(body: SaveRulesBody) -> Dict[str, Any]:
    """保存风险宪法（只收已知键，必须正数）。"""
    try:
        # exclude_none：未传的字段不进 save_rules（save_rules 对 None float() 会报错，
        # 区别于 save_fees 的 None→默认值兜底——rules 只改用户明确传的键）
        return await asyncio.to_thread(risk_rules.save_rules, body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, f"参数错误：{e}") from e


@router.get("/api/risk/equity-base")
async def risk_equity_base_get() -> Dict[str, Any]:
    """账户规模（用户自填，没填返 None——不用历史最大投入代替）。"""
    base = await asyncio.to_thread(at_risk.load_equity_base)
    return {"equity_base": base}


class EquityBaseBody(BaseModel):
    base: float


@router.post("/api/risk/equity-base")
async def risk_equity_base_set(body: EquityBaseBody) -> Dict[str, Any]:
    """设置账户规模。"""
    try:
        return await asyncio.to_thread(at_risk.save_equity_base, body.base)
    except ValueError as e:
        raise HTTPException(400, f"参数错误：{e}") from e


__all__ = ["router"]
