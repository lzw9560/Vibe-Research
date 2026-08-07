"""
Trading Workflow router.
Provides pre-market, intraday, and post-market workflow endpoints.
"""
import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Query
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import asdict
from pydantic import BaseModel

from trading_workflow import TradingWorkflow
from factors import registry as factor_registry
from factors.base import FactorResult
from vr_paths import last_trading_date_str
from strategies.strategy_matcher import StrategyMatcher
from strategies.position_advisor import PositionAdvisor
from limitup_strategy import StrategySignal
from risk.bomb_alert_system import BombAlertSystem
from risk.position_manager import PositionManager, PositionLimit
from settlement.settlement_engine import SettlementEngine
from win_rate_tracker import WinRateTracker, generate_strategy_adjustments
import workflow_state_repo as _wf_state_repo  # S032 R10：七态状态落库

router = APIRouter(tags=["workflow"])

_workflow = TradingWorkflow()

# S026: pre-market 异步采集内存缓存（进程重启丢，盘前每日重采可接受）
_cache: dict[str, Any] = {
    "run_id": None,
    "status": "idle",  # idle | running | done | error
    "factors": None,
    "data_date": None,
    "as_of": None,
    "market_emotion": None,
    "error": None,
}


def _now_iso() -> str:
    return datetime.now().isoformat()


async def _collect(run_id: str, target_date: str) -> None:
    """后台异步采集（S026）：to_thread 释放事件循环，afetch_all 并行两因子。"""
    try:
        factor_registry.register_default_factors()
        results = await factor_registry.afetch_all(target_date)
        me = await asyncio.to_thread(_fetch_market_emotion, target_date)
        _cache.update(
            run_id=run_id,
            status="done",
            factors=[_serialize_factor(r) for r in results],
            data_date=target_date,
            market_emotion=me,
            as_of=_now_iso(),
            error=None,
        )
    except Exception as exc:  # noqa: BLE001
        _cache.update(run_id=run_id, status="error", error=str(exc), as_of=_now_iso())


def _fetch_market_emotion(date: str) -> dict[str, Any]:
    """取当日市场情绪（复用 market 模块，失败降级）。"""
    try:
        import market
        ov = market.get_overview(date)
        return {"sentiment_index": (ov or {}).get("sentiment_index"), "phase": (ov or {}).get("phase")}
    except Exception:
        return {}


def _serialize_factor(fr: FactorResult) -> dict[str, Any]:
    """序列化 FactorResult 为前端可消费的 dict。"""
    return {
        "factor_id": fr.factor_id,
        "factor_name": fr.factor_name,
        "candidates": [
            {
                "code": c.code, "name": c.name,
                "source_factor_id": c.source_factor_id, "source_layer": c.source_layer,
                "hit_rules": c.hit_rules, "detail": c.detail,
            }
            for c in fr.candidates
        ],
        "layers": [l.model_dump(mode="json") for l in fr.layers],
        "config": fr.config,
        "as_of": fr.as_of,
        "data_date": fr.data_date,
        "data_status": fr.data_status,
    }
_strategy_matcher = StrategyMatcher()
_position_advisor = PositionAdvisor()
_bomb_alert_system = BombAlertSystem()
_position_manager = PositionManager(limits=PositionLimit())
_settlement_engine = SettlementEngine()
_win_rate_tracker = WinRateTracker()


def _serialize(obj: Any) -> Any:
    """递归序列化 dataclass / Pydantic model / 普通对象为 JSON 安全结构。"""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    if hasattr(obj, "__dict__"):
        return asdict(obj)
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(item) for item in obj]
    return obj


@router.get("/api/workflow/status")
async def get_workflow_status() -> Dict[str, Any]:
    """
    Get current workflow status based on market time.

    Returns the current stage (pre-market/intraday/post-market) and next stage info.
    """
    try:
        return {"data": _workflow.get_current_stage()}
    except Exception as e:
        raise HTTPException(500, f"获取工作流状态失败：{e}") from e


@router.get("/api/workflow/pre-market")
async def get_pre_market_workflow(date: Optional[str] = Query(None, description="日期，格式 YYYY-MM-DD；不传则取最近交易日")) -> Dict[str, Any]:
    """盘前简报（S026 异步化）：返回最近一次采集缓存。

    idle/无结果 → 提示先 refresh；running → 状态；done → factors；error → 错误。
    旧路径（请求即采集）已废弃：原同步 fetch_all 阻塞事件循环（health 卡死）。
    """
    status = _cache["status"]
    if status == "idle":
        return {
            "status": "idle",
            "msg": "未采集，请先 POST /api/workflow/pre-market/refresh",
            "data_date": None,
        }
    resp: dict[str, Any] = {
        "status": status,
        "data_date": _cache["data_date"],
        "as_of": _cache["as_of"],
        "market_emotion": _cache.get("market_emotion"),
        "run_id": _cache["run_id"],
    }
    if status == "done":
        resp["factors"] = _cache["factors"]
    elif status == "error":
        resp["error"] = _cache.get("error")
    return resp


@router.post("/api/workflow/pre-market/refresh")
async def refresh_pre_market(date: Optional[str] = Query(None, description="日期，格式 YYYY-MM-DD；不传则取最近交易日")) -> Dict[str, Any]:
    """触发后台异步采集（S026）：立即返回 run_id+status=running，不阻塞。

    并发守卫：status==running 时返"已有采集在跑"+现有 run_id
    （单事件循环下 check→set 之间无 await，原子；多 worker 才需外部协调，属 Celery/Redis TODO）。
    """
    target_date = date or last_trading_date_str()
    if _cache["status"] == "running":
        return {"run_id": _cache["run_id"], "status": "running", "msg": "已有采集在跑"}
    run_id = uuid.uuid4().hex[:8]
    _cache.update(run_id=run_id, status="running", data_date=target_date, error=None, as_of=_now_iso())
    asyncio.create_task(_collect(run_id, target_date))  # 后台跑，不 await
    return {"run_id": run_id, "status": "running"}


@router.post("/api/workflow/pre-market/run")
async def run_pre_market_workflow(date: Optional[str] = Query(None, description="日期，格式 YYYY-MM-DD；不传则取最近交易日")) -> Dict[str, Any]:
    """
    Manually trigger pre-market workflow.
    """
    try:
        workflow = TradingWorkflow(date=date)
        report = await workflow.run_pre_market()
        return {"data": _serialize(report)}
    except Exception as e:
        raise HTTPException(500, f"运行盘前工作流失败：{e}") from e


@router.get("/api/workflow/realtime")
async def get_realtime_workflow() -> Dict[str, Any]:
    """
    Get realtime workflow data.

    Includes realtime monitoring, bomb alerts, and position adjustments.
    """
    try:
        result = await _workflow.run_intraday()
        return {"data": _serialize(result)}
    except Exception as e:
        raise HTTPException(500, f"获取实时工作流失败：{e}") from e


# 向后兼容别名
@router.get("/api/workflow/intraday")
async def get_intraday_workflow_alias() -> Dict[str, Any]:
    """Alias for /api/workflow/realtime (backward compatibility)."""
    return await get_realtime_workflow()


@router.get("/api/workflow/post-market")
async def get_post_market_workflow() -> Dict[str, Any]:
    """
    Get post-market workflow data.

    Includes settlement results, LLM review, and win rate stats.
    """
    try:
        report = await _workflow.run_post_market()
        return {"data": _serialize(report)}
    except Exception as e:
        raise HTTPException(500, f"获取盘后工作流失败：{e}") from e


@router.post("/api/workflow/refresh")
async def refresh_workflow() -> Dict[str, Any]:
    """
    Manually trigger workflow refresh.
    """
    try:
        return {
            "data": {
                "refreshed_at": datetime.now().isoformat(),
                "status": "success",
            }
        }
    except Exception as e:
        raise HTTPException(500, f"刷新工作流失败：{e}") from e


@router.get("/api/workflow/signals")
async def get_realtime_signals() -> Dict[str, Any]:
    """
    Get realtime trading signals.

    Returns current signals from the intraday workflow.
    """
    try:
        signals = _workflow.intraday.signals
        return {"data": _serialize(signals)}
    except Exception as e:
        raise HTTPException(500, f"获取实时信号失败：{e}") from e


@router.get("/api/workflow/alerts")
async def get_bomb_alerts() -> Dict[str, Any]:
    """
    Get bomb alerts (炸板预警).

    Returns current alerts from the bomb alert system.
    """
    try:
        alerts = _bomb_alert_system.active_alerts()
        return {"data": _serialize(alerts)}
    except Exception as e:
        raise HTTPException(500, f"获取炸板预警失败：{e}") from e


@router.post("/api/workflow/settle")
async def settle_position() -> Dict[str, Any]:
    """
    Manually trigger position settlement.
    """
    try:
        report = await _workflow.run_post_market()
        return {"data": _serialize(report)}
    except Exception as e:
        raise HTTPException(500, f"结算失败：{e}") from e


@router.get("/api/workflow/strategies")
async def get_strategies() -> Dict[str, Any]:
    """
    Get list of 8 limit-up strategies.
    """
    try:
        strategies = _strategy_matcher.list_strategies()
        return {"data": {"strategies": strategies}}
    except Exception as e:
        raise HTTPException(500, f"获取战法列表失败：{e}") from e


@router.post("/api/workflow/strategies/{name}/match")
async def match_strategy(name: str, code: str = Query(..., description="股票代码")) -> Dict[str, Any]:
    """
    Match a specific strategy against a stock.
    """
    try:
        strategy_def = _strategy_matcher.get_strategy_by_code(name)
        if not strategy_def:
            raise HTTPException(404, f"战法 {name} 不存在")

        # 获取股票基因得分
        from limitup_screener.service import get_screener_result
        from limitup_screener.models import compute_gene_score
        import astock

        result = await get_screener_result()  # TODO: pass date
        gene = None
        for g in result.gene_scores:
            if g.code == code:
                gene = g
                break

        if gene is None:
            return {
                "data": {
                    "strategy": name,
                    "code": code,
                    "matched": False,
                    "message": "股票不在当前候选池中",
                }
            }

        signals = _strategy_matcher.match(gene)
        matched = [s for s in signals if s.strategy_code == name]

        return {
            "data": {
                "strategy": name,
                "code": code,
                "matched": len(matched) > 0,
                "signals": _serialize(matched),
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"战法匹配失败：{e}") from e


@router.get("/api/workflow/win-rate")
async def get_win_rate() -> Dict[str, Any]:
    """
    Get win rate statistics.
    """
    try:
        stats = _win_rate_tracker.get_stats(window_size=20)
        adjustments = generate_strategy_adjustments(stats)
        return {
            "data": {
                "overall": stats.win_rate,
                "by_strategy": stats.strategy_breakdown,
                "adjustments": adjustments,
            }
        }
    except Exception as e:
        raise HTTPException(500, f"获取胜率失败：{e}") from e


@router.get("/api/workflow/adjustments")
async def get_adjustments() -> Dict[str, Any]:
    """
    Get strategy adjustment suggestions.
    """
    try:
        stats = _win_rate_tracker.get_stats(window_size=20)
        adjustments = generate_strategy_adjustments(stats)
        return {"data": {"adjustments": adjustments}}
    except Exception as e:
        raise HTTPException(500, f"获取调整建议失败：{e}") from e


# ============ S032 R10：工作流状态（七态状态机落库） ============


class _TransitionRequest(BaseModel):
    """手动流转请求：code+date 定位状态行，target 为目标态。

    S033 R2：entry_price/exit_price/strategy 为用户自填操作记录
    （holding 买入价 / settled 卖出价 / 战法），可选填，None 不覆盖已有值。
    """
    code: str
    date: str
    target: str
    reason: str = ""
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    strategy: Optional[str] = None


@router.get("/api/workflow/state")
async def get_workflow_states(date: Optional[str] = Query(None, description="日期 YYYY-MM-DD；默认最近交易日")) -> Dict[str, Any]:
    """S032 R10：查询某日全部 (code) 的工作流状态 + 按态计数。"""
    try:
        d = date or last_trading_date_str()
        states = _wf_state_repo.list_states(d)
        counts: Dict[str, int] = {}
        for s in states:
            counts[s["status"]] = counts.get(s["status"], 0) + 1
        return {"data": {"date": d, "states": states, "counts": counts}}
    except Exception as e:
        raise HTTPException(500, f"获取工作流状态失败：{e}") from e


@router.post("/api/workflow/state/transition")
async def transition_workflow_state(req: _TransitionRequest) -> Dict[str, Any]:
    """S032 R10：手动流转（candidate→watching→monitoring→holding→settled）。

    盘中自动推进/盘后自动结算未实现（S012 桩范围），故除盘前自动落
    candidate/filtered 外，其余流转由用户按自己操作经本端点推进。
    非法流转 400，detail 带当前态与允许目标。
    """
    code = (req.code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "code 必须是 6 位数字")
    try:
        ok, detail = _wf_state_repo.transition(
            code, req.date, req.target, req.reason,
            entry_price=req.entry_price, exit_price=req.exit_price, strategy=req.strategy,
        )
    except Exception as e:
        raise HTTPException(500, f"工作流状态流转失败：{e}") from e
    if not ok:
        current = _wf_state_repo.get_state(code, req.date)
        raise HTTPException(400, {
            "error": detail,
            "current": current["status"] if current else None,
            "allowed_targets": _wf_state_repo.allowed_targets(code, req.date),
        })
    state = _wf_state_repo.get_state(code, req.date)
    return {"data": state}


@router.get("/api/workflow/state/{code}")
async def get_single_workflow_state(code: str, date: Optional[str] = Query(None, description="日期 YYYY-MM-DD；默认最近交易日")) -> Dict[str, Any]:
    """S033 R3：单股工作流状态 + 当前态允许的目标态（无记录 404）。

    路由顺序注意：本端点须先于 /state/{code}/history 注册（FastAPI 按注册序匹配）。
    """
    try:
        d = date or last_trading_date_str()
        result = _wf_state_repo.get_state_with_targets(code, d)
    except Exception as e:
        raise HTTPException(500, f"获取单股工作流状态失败：{e}") from e
    if result is None:
        raise HTTPException(404, f"该日无此股的工作流状态记录: code={code} date={d}")
    return {"data": result}


@router.get("/api/workflow/state/{code}/history")
async def get_workflow_state_history(code: str, date: Optional[str] = Query(None, description="日期 YYYY-MM-DD；不传则全部")) -> Dict[str, Any]:
    """S032 R10：某股流转历史（可按日期过滤）。"""
    try:
        history = _wf_state_repo.get_history(code, date)
        return {"data": {"code": code, "date": date, "history": history}}
    except Exception as e:
        raise HTTPException(500, f"获取流转历史失败：{e}") from e


__all__ = ["router"]
