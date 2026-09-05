"""S149 Phase 3 P3-T5 — 交易日志 + 个人风控路由（journal 7 + risk 9 端点）。

audit §3 契约。与既有 routers/risk.py（市场级风险 dashboard/seats/bomb-alerts/…）
路径无碰撞（不同 path），分文件命名空间隔离（#7）。

⛔ 所有端点返个人交易数据——**不接入 AI prompt**（P3-T1 闭包扫描锁定：
本路由不 import chat/ai.tools；journal/at_risk/risk_rules/excursion/attribution/
inbox 均在 denylist）。只读 API 给前端渲染，AI 永远看不到。

# derived from vibe-astock@3c3b7c8 (github.com/lzw9560), Apache-2.0, modified
"""
from __future__ import annotations

from typing import Any, Dict

import asyncio
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import journal
import at_risk
import risk_rules
import excursion
import attribution
import inbox

router = APIRouter(tags=["journal"])


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

    S149 P3 审查修复：用 model_fields_set 区分「字段未传」(保持原值 _UNSET) vs
    「显式传 null」(清空)——Pydantic 二者都反序列化为 None，旧写法把 null 当未传
    → as_planned/planned_stop/planned_target 无法经 API 清空（null 仍保持原值）。
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
    """在险资金：当前持仓最坏情况亏多少（bounded 合计 + unbounded 单独报）。"""
    return await asyncio.to_thread(at_risk.report)


@router.get("/api/risk/excursion")
async def risk_excursion(limit: int = Query(300, ge=1, le=5000)) -> Dict[str, Any]:
    """MFE/MAE 汇总（逐笔拉行情，单独端点不进 report——首次慢）。"""
    return await asyncio.to_thread(excursion.summary, limit)


@router.get("/api/risk/attribution")
async def risk_attribution(limit: int = Query(500, ge=1, le=5000)) -> Dict[str, Any]:
    """判断/执行归因四格（⚠️ Vibe-Research 暂无 reflection 数据→降级 available:False）。"""
    return await asyncio.to_thread(attribution.attribution, limit)


@router.get("/api/risk/inbox")
async def risk_inbox(limit: int = Query(500, ge=1, le=5000)) -> Dict[str, Any]:
    """异常交易收件箱（按自设阈值 + 自中位偏离筛，不排严重程度）。"""
    return await asyncio.to_thread(inbox.build, limit)


@router.get("/api/risk/rules")
async def risk_rules_get() -> Dict[str, Any]:
    """风险宪法（用户自设阈值；is_default 标是否初值）。"""
    return await asyncio.to_thread(risk_rules.load_rules)


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
