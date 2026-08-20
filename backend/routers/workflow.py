"""
Trading Workflow router.
Provides pre-market, intraday, and post-market workflow endpoints.
"""
import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, HTTPException, Query
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import dataclasses
from dataclasses import asdict
from pydantic import BaseModel

from trading_workflow import TradingWorkflow
from factors import registry as factor_registry
from factors.base import FactorResult
from vr_paths import last_trading_date_str, resolve_data_dir
from candidate_funnel import funnel as funnel_mod
from strategies.strategy_matcher import StrategyMatcher
from strategies.position_advisor import PositionAdvisor
from limitup_strategy import StrategySignal
from risk.bomb_alert_system import BombAlertSystem
from risk.position_manager import PositionManager, PositionLimit
from settlement.settlement_engine import SettlementEngine
from win_rate_tracker import WinRateTracker, generate_strategy_adjustments
from sentiment_context import SentimentContext, build_context  # S063 T2/T4：管线头部情绪上下文
import workflow_state_repo as _wf_state_repo  # S032 R10：七态状态落库
import settlement_recorder as _settlement_recorder  # S034：settled 流转即结算
from market_price import fetch_current_price  # S038：settled 时自动拉市价填 exit_price

logger = logging.getLogger(__name__)
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
    "sentiment_context": None,  # S063 T4：管线头部情绪上下文（T-1）
    "error": None,
}

# S068 R2：保留后台采集 task 的强引用，防 CPython GC 在 task 挂起（await/to_thread）时回收。
# done 回调从 set 中移除，避免无限增长。对照 intraday_sentiment._task 的正确范式。
_pending_collections: set[asyncio.Task] = set()

# ============ S048 R4：盘前快照持久化（历史不可变，纯读盘零请求） ============
# S050：读侧（_load_snapshot/_list_snapshot_dates）抽至 snapshot_store.py 共用；
# _save_snapshot 仍留此处（写盘是采集链路职责，settlement 只读不写）。

_SNAPSHOT_SCHEMA = "v1"

from snapshot_store import load_snapshot as _load_snapshot, list_snapshot_dates as _list_snapshot_dates  # noqa: E402


def _snapshot_dir() -> Path:
    """快照目录：<私有数据根>/workflow/pre-market/（VR_DATA_DIR 可覆盖，conftest 已隔离）。

    保留供 _save_snapshot 写盘用；读侧已迁 snapshot_store。
    """
    return resolve_data_dir() / "workflow" / "pre-market"


def _snapshot_path(date: str) -> Path:
    """快照文件路径：<快照目录>/<date>.json。"""
    return _snapshot_dir() / f"{date}.json"


def _is_valid_date(d: str) -> bool:
    try:
        datetime.strptime(d, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


def _json_default(obj):
    """json.dumps 兜底：裸 Pydantic/dataclass 对象降级为 dict，避免整体写盘失败。

    防御纵深——源头已剥 dataclass（strategy_funnel_registry），此层兜未来其他混入。
    """
    if hasattr(obj, "model_dump"):       # Pydantic v2（项目既有范式 workflow.py:418）
        return obj.model_dump(mode="json")
    if dataclasses.is_dataclass(obj):     # 裸 dataclass（PositionParams 等）
        return dataclasses.asdict(obj)
    return str(obj)                       # 末路：防崩，schema 不可控但至少落盘


def _save_snapshot(payload: dict) -> None:
    """整体原子写盘（临时文件 rename，避免半截 JSON）；文件名取 payload[data_date]。"""
    date = payload.get("data_date", "")
    if not _is_valid_date(date):
        raise ValueError(f"快照 data_date 非法: {date!r}")
    d = _snapshot_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{date}.tmp"
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, default=_json_default),
        encoding="utf-8",
    )
    tmp.replace(d / f"{date}.json")


def _build_funnel_layers(date: str, ctx: "SentimentContext | None" = None) -> list[dict]:
    """当日漏斗层（随快照落盘 → 历史视角纯读盘，零外部请求）。

    config 取 candidates 路由的 live config（用户调参后一致，同 topology
    _load_candidates 范式）；失败返空列表，不影响采集 done。

    S063 T4：ctx 下传给 run_funnel（weather_state/source_date）。
    """
    try:
        from routers.candidates import _store  # noqa: PLC0415 — lazy import 防循环，运行时取 live config
        result = funnel_mod.run_funnel("all", date, _store["config"], ctx)
        return [l.model_dump(mode="json") for l in result.layers]
    except Exception as exc:  # noqa: BLE001
        logger.warning("funnel_layers 构建失败 (%s): %s", date, exc)
        return []


def _now_iso() -> str:
    return datetime.now().isoformat()


async def _collect(run_id: str, target_date: str) -> None:
    """后台异步采集（S026）：to_thread 释放事件循环，afetch_all 并行两因子。

    S048 R4：done 后整体按日落盘快照（含漏斗层）；写盘失败不影响内存 done。
    S063 T4：管线头部构造 SentimentContext（T-1 一次采集），下传给
    _fetch_market_emotion / _build_funnel_layers / match_strategy / PositionAdvisor。
    """
    try:
        factor_registry.register_default_factors()
        results = await factor_registry.afetch_all(target_date)
        # S063 T4：管线头部一次采集 SentimentContext（T-1 硬标准）
        ctx = await asyncio.to_thread(build_context, target_date)
        me = await asyncio.to_thread(_fetch_market_emotion, target_date, ctx)
        funnel_layers = await asyncio.to_thread(_build_funnel_layers, target_date, ctx)
        as_of = _now_iso()
        factors = [_serialize_factor(r) for r in results]
        # B-lite：战法打分接入 briefing 响应供前端 tab 过滤。
        # score_candidates 入参需 {code, name, factors(中文键名 dict), total_score, zt_count_250d}。
        # 数据源选 load_gene_scores（sync DB 读，快；与 funnel.fetch_genes 同源，不重复外部请求）。
        # forward_test.py:464-470 原用 getattr(g,"factor_seal_rate",0) 映射因子是脏数据
        # （GeneScore 无英文 factor_* 属性，恒取默认 0）；已修复为 (g.factors or {}).get("中文键",0)
        # →英文键名映射，与 backtest_lite.py:118 范式一致。
        # 此处直接透传 g.factors（中文键名 dict，score_candidates/test_strategy_funnel_registry 同款口径）。
        scored_candidates: list[dict] = []
        try:
            from limitup_screener.data import load_gene_scores
            from strategies.strategy_funnel_registry import score_candidates
            genes = await asyncio.to_thread(load_gene_scores, target_date)
            if genes:
                # S073 修数据链断：scored 用 R3 幸存者（非 DB 全量），R3→scored 真串联
                r3_layer = next((l for l in (funnel_layers or []) if l.get("layer_id") == "R3"), None)
                r3_codes = set(r3_layer.get("output_codes", []) if r3_layer else [])
                if r3_codes:
                    genes_filtered = [g for g in genes if g.code in r3_codes]
                    logger.info("scored 接 R3：%d 只幸存者（原全量 %d）", len(genes_filtered), len(genes))
                    genes = genes_filtered
                else:
                    logger.info("R3 无幸存者或无 R3 层，scored 降级全量 %d 只", len(genes))
                cand_input = [
                    {
                        "code": g.code,
                        "name": getattr(g, "name", ""),
                        "factors": getattr(g, "factors", {}) or {},
                        "total_score": getattr(g, "total_score", 0) or 0,
                        "zt_count_250d": getattr(g, "zt_count_250d", 0) or 0,
                    }
                    for g in genes
                ]
                weather_state = ctx.weather_state if ctx else None
                # S086 R7：取涨停池建 pool_item_map 传给 score_candidates，
                # 供 storm_reversal(fbt)/PRD 战法(lbc/zdp/p) 取因子 + R2 真实入场价 pool_item.p。
                # fetch_zt_pool → em_zt_topic_pool 走 em_get 限流 + 24h 缓存（防封底线）；
                # 失败/空池 → 空 map 降级，entry_price fallback gene.total_score + "价格代理"（A7）。
                pool_item_map: dict[str, dict] = {}
                try:
                    from strategies.first_board_filter import fetch_zt_pool  # noqa: PLC0415
                    zt_pool = await asyncio.to_thread(fetch_zt_pool, target_date)
                    for p in zt_pool or []:
                        code = str(p.get("c", "") or "").strip()
                        if code:
                            pool_item_map[code] = p
                except Exception as exc:  # noqa: BLE001 — 取池失败降级空 map，不阻断 briefing
                    logger.warning("scored 取涨停池建 pool_item_map 失败 %s: %s", target_date, exc)
                scored = await asyncio.to_thread(
                    score_candidates, cand_input, weather_state, target_date, pool_item_map,
                )
                # 过滤"无符合条件标的"占位项（strategy_code="none"）
                scored_candidates = [s for s in scored if s.get("strategy_code") != "none"]
        except Exception as exc:  # noqa: BLE001 — 打分失败不影响 briefing 主态
            logger.warning("scored_candidates 构建失败 %s: %s", target_date, exc)

        # S079 D1：从 limitup_screener factor 的 config 提取 P2 仓位闸 + 龙虎榜风控字段
        # PreMarketWorkflow.run() 在 LimitupScreenerFactor.fetch 内被调用，P2 字段塞 config_out
        # → _serialize_factor 透传 → 这里提取到 _cache 顶层供响应直接消费
        p2_fields = _extract_p2_fields(results)
        _cache.update(
            run_id=run_id,
            status="done",
            factors=factors,
            data_date=target_date,
            market_emotion=me,
            sentiment_context=ctx.to_dict(),
            as_of=as_of,
            error=None,
            scored_candidates=scored_candidates,
            # S079 P2 顶层字段（供 get_pre_market_workflow 响应直接透传）
            market_phase=p2_fields.get("market_phase"),
            market_phase_cap=p2_fields.get("market_phase_cap"),
            position_cap_tier=p2_fields.get("position_cap_tier"),
            seat_risk_flags=p2_fields.get("seat_risk_flags", {}),
            data_missing_flags=p2_fields.get("data_missing_flags", {}),
            execution_checklist=p2_fields.get("execution_checklist", []),
            param_disclaimer=p2_fields.get("param_disclaimer"),
        )
        # S049 D6：done 即清 funnel 缓存（防跨 run 串数据；下次 GET 走 _build_funnel_layers 重建）
        funnel_mod.clear_funnel_cache(target_date)
        try:
            # S049 C4：快照存 final_candidates 诊断卡（抽屉查看历史快照日期时优先用，无才 live diagnose）
            final_cards: list[dict] = []
            try:
                from routers.candidates import _store  # noqa: PLC0415
                result = funnel_mod.run_funnel("all", target_date, _store["config"], ctx)
                final_cards = [c.model_dump(mode="json") for c in result.final_candidates]
            except Exception as exc:  # noqa: BLE001 — 诊断卡构建失败不影响快照主态
                logger.warning("final_candidates 诊断卡构建失败 %s: %s", target_date, exc)
            _save_snapshot({
                "schema": _SNAPSHOT_SCHEMA,
                "data_date": target_date,
                "as_of": as_of,
                "run_id": run_id,
                "market_emotion": me,
                "sentiment_context": ctx.to_dict(),
                "factors": factors,
                "funnel_layers": funnel_layers,
                "final_candidates": final_cards,
                "scored_candidates": scored_candidates,
                # 补采标记：采集时刻 target_date 早于最近交易日
                "is_backfill": target_date < last_trading_date_str(),
                # S079 P2 仓位闸 + 龙虎榜风控字段（历史快照同结构）
                "market_phase": p2_fields.get("market_phase"),
                "market_phase_cap": p2_fields.get("market_phase_cap"),
                "position_cap_tier": p2_fields.get("position_cap_tier"),
                "seat_risk_flags": p2_fields.get("seat_risk_flags", {}),
                "data_missing_flags": p2_fields.get("data_missing_flags", {}),
                "execution_checklist": p2_fields.get("execution_checklist", []),
                "param_disclaimer": p2_fields.get("param_disclaimer"),
            })
        except Exception as exc:  # noqa: BLE001 — 落盘失败不影响内存态
            logger.warning("快照写盘失败 %s: %s", target_date, exc)
    except Exception as exc:  # noqa: BLE001
        _cache.update(run_id=run_id, status="error", error=str(exc), as_of=_now_iso())


def _extract_p2_fields(results: list) -> dict[str, Any]:
    """S079 D1：从 factor_registry 结果提取 P2 仓位闸 + 龙虎榜风控字段。

    PreMarketWorkflow.run() 在 LimitupScreenerFactor.fetch 内被调用，
    P2 字段塞 config_out（factors/limitup_screener_factor.py）→
    FactorResult.config → 这里提取。

    Args:
        results: factor_registry.afetch_all 返回的 FactorResult 列表

    Returns:
        dict 含 market_phase/market_phase_cap/position_cap_tier/
        seat_risk_flags/data_missing_flags/execution_checklist/param_disclaimer。
        找不到 limitup_screener factor 时返回全空（不阻塞主流程）。
    """
    p2_keys = (
        "market_phase", "market_phase_cap", "position_cap_tier",
        "seat_risk_flags", "data_missing_flags", "execution_checklist",
        "param_disclaimer",
    )
    for fr in results or []:
        factor_id = getattr(fr, "factor_id", "") or (fr.get("factor_id") if isinstance(fr, dict) else "")
        if factor_id == "limitup_screener":
            cfg = getattr(fr, "config", None) or (fr.get("config") if isinstance(fr, dict) else {}) or {}
            return {k: cfg.get(k) for k in p2_keys}
    # 找不到 → 全 None（降级，不阻塞）
    return {k: None for k in p2_keys}


def _fetch_market_emotion(date: str, ctx: "SentimentContext | None" = None) -> dict[str, Any]:
    """取当日市场情绪（STI 分数+阶段 + 三率 + ladder + 涨跌停家数）。

    S063 T4：重写为 T-1 视角——盘前读 T-1 的 STI timeline 行（不调
    get_market_emotion_raw(T) 盘前必空）。SentimentContext 已在管线头部构造，
    这里从 ctx 取 weather/sti_score/sti_phase；三率/ladder/zt_count/dt_count 从
    sti_timeline T-1 行的 dimension_* 字段映射（spec §10.1）。

    ladder 无法从 sti_timeline 重建（需原始涨停池明细），降级为 ladder=[] +
    标注"T-1 连板梯队未持久化"。

    ctx=None 时降级到旧路径（调 get_market_emotion_raw + engine.compute，
    供未接 ctx 的调用方/测试 mock）。

    返回 shape：
      {sti_score, sti_phase, seal_rate, break_rate, promotion_rate,
       ladder, zt_count, dt_count, weather_state, sentiment_source}
    任一数据源失败 → 对应字段 None，不崩。
    """
    # S063 T4：ctx 优先（管线头部一次采集，逐级下传）
    if ctx is not None:
        return _market_emotion_from_ctx(date, ctx)

    out: dict[str, Any] = {
        "sti_score": None, "sti_phase": None,
        "seal_rate": None, "break_rate": None, "promotion_rate": None,
        "ladder": [], "zt_count": None, "dt_count": None,
        "weather_state": None, "sentiment_source": None,
    }
    from candidate_funnel.sources.board_ladder import get_market_emotion_raw  # noqa: PLC0415
    emo = get_market_emotion_raw(date)
    if emo:
        out["seal_rate"] = emo.get("seal_rate")
        out["break_rate"] = emo.get("break_rate")
        out["promotion_rate"] = emo.get("promotion_rate")
        out["ladder"] = emo.get("ladder") or []
        out["zt_count"] = emo.get("zt_count")
        out["dt_count"] = emo.get("dt_count")
    # STI 复用同一份 emotion（不重复外调），失败降级 None
    try:
        from limitup_sti.service import get_sti_engine  # noqa: PLC0415
        engine = get_sti_engine()
        import market
        sentiment = market._sentiment(date) or {}
        sti = engine.compute(emo, sentiment)
        if sti.source_ok:
            out["sti_score"] = sti.score
            out["sti_phase"] = sti.phase.value if sti.phase else None
    except Exception:
        pass
    return out


def _market_emotion_from_ctx(date: str, ctx: "SentimentContext") -> dict[str, Any]:
    """从 SentimentContext（T-1 STI 行）映射为 _fetch_market_emotion 输出 shape。

    S063 T4 + spec §10.1：sti_timeline 存 8 个 dimension_* 归一化值（0-100），
    简报需要 seal_rate（0-1 比率）等 → dimension 值 /100 显示。
    ladder 无法重建 → [] + 标注"T-1 连板梯队未持久化"。
    """
    out: dict[str, Any] = {
        "sti_score": ctx.sti_score,
        "sti_phase": ctx.sti_phase,
        "seal_rate": None, "break_rate": None, "promotion_rate": None,
        "ladder": [], "zt_count": None, "dt_count": None,
        "weather_state": ctx.weather_state,
        "sentiment_source": f"T-1({ctx.source_date})" if ctx.source_date else "T-1(missing)",
    }
    if ctx.data_status != "ok":
        out["ladder_note"] = "情绪数据未取得（T-1 STI 缺失）"
        return out

    # 从 sti_timeline T-1 行映射三率/涨跌停家数
    try:
        from limitup_sti.data import get_db  # noqa: PLC0415
        db = get_db()
        row = db.execute(
            "SELECT * FROM sti_timeline WHERE date = ?",
            (ctx.source_date,),
        ).fetchone()
        if row is None:
            out["ladder_note"] = "T-1 连板梯队未持久化"
            return out

        def _dim(name: str) -> float | None:
            v = row[name] if name in row.keys() else None
            return float(v) if v is not None else None

        # dimension_* 是 0-100 归一化值；简报三率按 0-1 比率展示 → /100
        seal = _dim("dimension_seal_rate")
        promo = _dim("dimension_promotion_rate")
        zt = _dim("dimension_limit_up_count")
        dt = _dim("dimension_limit_down_count")

        out["seal_rate"] = round(seal / 100, 3) if seal is not None else None
        out["promotion_rate"] = round(promo / 100, 3) if promo is not None else None
        out["zt_count"] = zt
        out["dt_count"] = dt
        # S063 T4 补齐：raw_break_rate 由 compute 落库（market._emotion 算出的原始 0-1 比率），
        # 历史行无此列 → _dim 返 None → 简报显示 "--"（诚实标注而非臆造 0）。
        raw_br = _dim("raw_break_rate")
        out["break_rate"] = round(raw_br, 3) if raw_br is not None else None
        out["break_rate_note"] = None if raw_br is not None else "T-1 炸板率未持久化（历史行无 raw_break_rate 列）"
        out["ladder_note"] = "T-1 连板梯队未持久化"
    except Exception as exc:  # noqa: BLE001
        out["ladder_note"] = f"T-1 映射失败: {exc}"
    return out


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


def _not_implemented(message: str, spec: str = "S036") -> Dict[str, Any]:
    """S036：桩端点标灰——返回结构化 not_implemented 状态，不跑桩逻辑。

    端点签名/路由路径不变（契约兼容）；调用方拿到结构化降级而非 500。
    桩方法（realtime_workflow / post_market_workflow）保留签名但端点已 early
    return 不触达——见 S036 R7。
    """
    return {"not_implemented": True, "message": message, "spec": spec}


@router.get("/api/workflow/status")
def get_workflow_status() -> Dict[str, Any]:
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
    """盘前简报（S026 异步化 + S048 历史视角）：内存态优先，历史读盘上快照。

    级联（S048 R5）：
    ① 内存 data_date==date 且 running/done/error → 返内存态；
    ② 内存 data_date==date 且 idle → idle 提示；
    ③ 盘上有快照 → done + from_snapshot=true（纯读盘零请求）；
    ④ date==最近交易日 → idle（当日可采集）；
    ⑤ 否则 → no_snapshot（需显式补采）。
    """
    d = date or last_trading_date_str()
    if not _is_valid_date(d):
        raise HTTPException(400, f"日期格式错误（应为 YYYY-MM-DD）：{date}")

    if _cache["data_date"] == d:
        status = _cache["status"]
        if status == "idle":
            # 闭环降级：idle 也降级 build_context 返天气条数据，避免前端"未取得"
            try:
                ctx = await asyncio.to_thread(build_context, d)
                return {
                    "status": "idle",
                    "msg": "未采集，请先 POST /api/workflow/pre-market/refresh",
                    "data_date": None,
                    "sentiment_context": ctx.to_dict(),
                }
            except Exception as exc:  # noqa: BLE001
                logger.warning("idle 降级 build_context 失败 %s: %s", d, exc)
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
            "sentiment_context": _cache.get("sentiment_context"),  # S063 T4：管线头部情绪上下文
            "run_id": _cache["run_id"],
        }
        if status == "done":
            resp["factors"] = _cache["factors"]
            # B-lite：透传 scored_candidates 供前端战法 tab 过滤
            resp["scored_candidates"] = _cache.get("scored_candidates", [])
            # S049 D4：live done 透出 funnel_layers（与快照路径对齐；_build_funnel_layers 命中 run_funnel 缓存不重复请求）
            # S063 T4：ctx 下传——live done 时重建 ctx（T-1 硬标准，幂等）
            ctx = await asyncio.to_thread(build_context, d)
            funnel_layers = await asyncio.to_thread(_build_funnel_layers, d, ctx)
            resp["funnel_layers"] = funnel_layers
            # ctx 可能与采集时存的不完全一致（T-1 STI 被重算）→ 以最新 ctx 为准
            resp["sentiment_context"] = ctx.to_dict()
            # S079 D1：透传 P2 仓位闸 + 龙虎榜风控字段到响应顶层
            resp["market_phase"] = _cache.get("market_phase")
            resp["market_phase_cap"] = _cache.get("market_phase_cap")
            resp["position_cap_tier"] = _cache.get("position_cap_tier")
            resp["seat_risk_flags"] = _cache.get("seat_risk_flags", {})
            resp["data_missing_flags"] = _cache.get("data_missing_flags", {})
            resp["execution_checklist"] = _cache.get("execution_checklist", [])
            resp["param_disclaimer"] = _cache.get("param_disclaimer")
        elif status == "error":
            resp["error"] = _cache.get("error")
        return resp

    snap = _load_snapshot(d)
    if snap is not None:
        # S063 T4：快照无 sentiment_context 时（旧快照）降级重建
        sent_ctx = snap.get("sentiment_context")
        if sent_ctx is None:
            try:
                ctx = await asyncio.to_thread(build_context, d)
                sent_ctx = ctx.to_dict()
            except Exception as exc:  # noqa: BLE001
                logger.warning("快照 sentiment_context 重建失败 %s: %s", d, exc)
        return {
            "status": "done",
            "from_snapshot": True,
            "data_date": snap.get("data_date", d),
            "as_of": snap.get("as_of"),
            "run_id": snap.get("run_id"),
            "market_emotion": snap.get("market_emotion"),
            "sentiment_context": sent_ctx,
            "factors": snap.get("factors", []),
            "funnel_layers": snap.get("funnel_layers", []),
            "scored_candidates": snap.get("scored_candidates", []),
            "is_backfill": snap.get("is_backfill", False),
            # S079 D1：历史快照同结构透传 P2 字段（旧快照无此字段时降级 None/空）
            "market_phase": snap.get("market_phase"),
            "market_phase_cap": snap.get("market_phase_cap"),
            "position_cap_tier": snap.get("position_cap_tier"),
            "seat_risk_flags": snap.get("seat_risk_flags", {}),
            "data_missing_flags": snap.get("data_missing_flags", {}),
            "execution_checklist": snap.get("execution_checklist", []),
            "param_disclaimer": snap.get("param_disclaimer"),
        }

    if d == last_trading_date_str():
        # 闭环降级：当日 idle 也降级 build_context 返天气条数据，避免前端"未取得"
        try:
            ctx = await asyncio.to_thread(build_context, d)
            return {
                "status": "idle",
                "msg": "未采集，请先 POST /api/workflow/pre-market/refresh",
                "data_date": None,
                "sentiment_context": ctx.to_dict(),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("当日 idle 降级 build_context 失败 %s: %s", d, exc)
            return {
                "status": "idle",
                "msg": "未采集，请先 POST /api/workflow/pre-market/refresh",
                "data_date": None,
            }

    return {
        "status": "no_snapshot",
        "msg": f"{d} 无采集快照，可显式补采（补采数据可能与当日所见有出入）",
        "data_date": d,
    }


@router.get("/api/workflow/pre-market/dates")
def get_pre_market_dates() -> Dict[str, Any]:
    """S048 R5：有快照的日期降序列表（供日期选择器标注）。"""
    return {"dates": _list_snapshot_dates()}


@router.post("/api/workflow/pre-market/refresh")
async def refresh_pre_market(date: Optional[str] = Query(None, description="日期，格式 YYYY-MM-DD；不传则取最近交易日")) -> Dict[str, Any]:
    """触发后台异步采集（S026）：立即返回 run_id+status=running，不阻塞。

    并发守卫：status==running 时返"已有采集在跑"+现有 run_id
    （单事件循环下 check→set 之间无 await，原子；多 worker 才需外部协调，属 Celery/Redis TODO）。
    """
    target_date = date or last_trading_date_str()
    # I2：历史不可变守卫——盘上已有该日快照且为历史日期（< 最近交易日）→ 拒绝覆写。
    # 今日（== 最近交易日）允许重采（当日采集可更新）；历史无快照允许补采（no_snapshot 链路）。
    if target_date < last_trading_date_str() and _load_snapshot(target_date) is not None:
        raise HTTPException(409, f"{target_date} 历史快照已存在，不可覆写（历史不可变；补采请先删快照）")
    if _cache["status"] == "running":
        return {"run_id": _cache["run_id"], "status": "running", "msg": "已有采集在跑"}
    run_id = uuid.uuid4().hex[:8]
    _cache.update(run_id=run_id, status="running", data_date=target_date, error=None, as_of=_now_iso())
    # S068 R2：保留强引用防 CPython GC 在 task 挂起（await/to_thread）时回收；
    # done 回调从 set 移除，避免无限增长。
    task = asyncio.create_task(_collect(run_id, target_date))
    _pending_collections.add(task)
    task.add_done_callback(_pending_collections.discard)
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
def get_realtime_workflow() -> Dict[str, Any]:
    """盘中监控未实现（S036 标灰）——不跑 run_intraday 桩，返回结构化降级。"""
    return _not_implemented("盘中监控未实现")


# 向后兼容别名
@router.get("/api/workflow/intraday")
async def get_intraday_workflow_alias() -> Dict[str, Any]:
    """Alias for /api/workflow/realtime (backward compatibility)."""
    # get_realtime_workflow 是 sync（返 _not_implemented 降级），不能 await
    return get_realtime_workflow()


@router.get("/api/workflow/post-market")
def get_post_market_workflow() -> Dict[str, Any]:
    """盘后复盘未实现（S036 标灰）——不跑 run_post_market 桩，返回结构化降级。"""
    return _not_implemented("盘后复盘未实现")


@router.get("/api/workflow/verification-card")
def get_verification_card(date: str = Query(None, description="交易日 YYYY-MM-DD；不传取最近交易日")) -> Dict[str, Any]:
    """S060：明日验证条件对账卡——返当日生成 + 对账结果。

    缺数据条件 status=data_missing 诚实标注，不臆造。
    """
    try:
        from workflow.verification_card import get_conditions
        from vr_paths import last_trading_date_str
        target = date or last_trading_date_str()
        conditions = get_conditions(target)
        status_counts = {
            "pending": sum(1 for c in conditions if c.get("status") == "pending"),
            "met_up": sum(1 for c in conditions if c.get("status") == "met_up"),
            "met_down": sum(1 for c in conditions if c.get("status") == "met_down"),
            "within": sum(1 for c in conditions if c.get("status") == "within"),
            "data_missing": sum(1 for c in conditions if c.get("status") == "data_missing"),
        }
        return {
            "data": {
                "date": target,
                "conditions": conditions,
                "count": len(conditions),
                "status_summary": status_counts,
                "note": "验证条件属客观统计口径，条件句式为「若…则确认…」，无涨跌预测；历史统计特征，市场有风险",
            }
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"验证对账卡查询异常：{e}") from e


@router.post("/api/workflow/verification-card/generate")
def generate_verification_card(date: str = Query(None, description="生成日 YYYY-MM-DD；不传取最近交易日")) -> Dict[str, Any]:
    """S060：手动触发条件生成（盘后调度自动跑，此端点供手动补跑）。"""
    try:
        from workflow.verification_card import generate_and_save
        from vr_paths import last_trading_date_str
        import market
        target = date or last_trading_date_str()
        emotion = market._emotion(target)
        if not emotion:
            return {"data": {"date": target, "generated": 0, "note": "情绪数据未取得，未生成条件"}}
        conditions = generate_and_save(emotion, target)
        return {
            "data": {
                "date": target,
                "generated": len(conditions),
                "conditions": [{"metric": c.metric, "baseline": c.baseline,
                                "threshold_up": c.threshold_up, "threshold_down": c.threshold_down,
                                "note": c.note} for c in conditions],
            }
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"验证条件生成异常：{e}") from e


@router.post("/api/workflow/verification-card/verify")
def verify_verification_card() -> Dict[str, Any]:
    """S060：手动触发 T+1 对账（盘后调度自动跑，此端点供手动补跑）。"""
    try:
        from workflow.verification_card import verify_and_update
        verified = verify_and_update()
        return {
            "data": {
                "verified": len(verified),
                "conditions": [{"date": c.date, "metric": c.metric, "actual": c.actual,
                                "status": c.status, "note": c.note} for c in verified],
            }
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"验证对账异常：{e}") from e


@router.post("/api/workflow/refresh")
def refresh_workflow() -> Dict[str, Any]:
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
def get_realtime_signals() -> Dict[str, Any]:
    """盘中信号未实现（S036 标灰）——不读 intraday.signals 桩，返回结构化降级。"""
    return _not_implemented("盘中信号未实现")


@router.get("/api/workflow/alerts")
def get_bomb_alerts() -> Dict[str, Any]:
    """炸板预警未实现（S036 标灰）——不读 active_alerts 桩，返回结构化降级。"""
    return _not_implemented("炸板预警未实现")


@router.post("/api/workflow/settle")
def settle_position() -> Dict[str, Any]:
    """盘后批量结算未实现（S036 标灰）——用状态机流转 settled 触发结算（见 S034）。"""
    return _not_implemented("盘后批量结算未实现，请用状态机流转 settled 触发结算（S034）")


@router.get("/api/workflow/strategies")
def get_strategies() -> Dict[str, Any]:
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

        # S063 T7：传 ctx.weather_state 给 StrategyMatcher 标注 weather_fit
        ctx = await asyncio.to_thread(build_context, last_trading_date_str())
        signals = _strategy_matcher.match(gene, ctx.weather_state)
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
def get_win_rate() -> Dict[str, Any]:
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
def get_adjustments() -> Dict[str, Any]:
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
    auto_fill_exit_price: bool = False  # S038：true=exit_price 空时后端自动拉市价
    attention_mode: Optional[str] = None  # S050 W0：用户自填关注模式 A/B/C（结算透传 winrate_records）


@router.get("/api/workflow/state")
def get_workflow_states(date: Optional[str] = Query(None, description="日期 YYYY-MM-DD；默认最近交易日")) -> Dict[str, Any]:
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
def transition_workflow_state(req: _TransitionRequest) -> Dict[str, Any]:
    """S032 R10：手动流转（candidate→watching→monitoring→holding→settled）。

    盘中自动推进/盘后自动结算未实现（S012 桩范围），故除盘前自动落
    candidate/filtered 外，其余流转由用户按自己操作经本端点推进。
    非法流转 400，detail 带当前态与允许目标。
    """
    code = (req.code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "code 必须是 6 位数字")
    # S038：settled 流转 + exit_price 空 + auto_fill=true → 拉市价预填 req.exit_price。
    # 拉到价则经下方 _wf_state_repo.transition(exit_price=...) 自然落库；拉不到 req.exit_price
    # 仍为 None，_settle_on_transition 走 S034 既有"缺价跳过"路径。
    exit_price_source: Optional[str] = None
    if (
        req.target == "settled"
        and req.auto_fill_exit_price
        and req.exit_price is None
    ):
        market_price = fetch_current_price(code)
        if market_price is not None:
            req.exit_price = market_price
            exit_price_source = "market"
    elif req.target == "settled" and req.exit_price is not None:
        exit_price_source = "manual"
    try:
        ok, detail = _wf_state_repo.transition(
            code, req.date, req.target, req.reason,
            entry_price=req.entry_price, exit_price=req.exit_price, strategy=req.strategy,
            attention_mode=req.attention_mode,
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
    # S034 R3：settled 流转即结算（价齐 + settled_at 幂等锚点）
    if req.target == "settled" and state is not None:
        settlement, settled_at = _settle_on_transition(code, req.date, state, exit_price_source)
        state["settlement"] = settlement
        if settled_at:
            state["settled_at"] = settled_at  # 落戳发生在 state 取数之后，回填响应
    return {"data": state}


def _settle_on_transition(
    code: str,
    date: str,
    state: Dict[str, Any],
    exit_price_source: Optional[str] = None,
) -> tuple[Dict[str, Any], Optional[str]]:
    """S034：settled 流转触发结算——写 winrate.db + 落 settled_at 锚点。

    价缺 → 不结算（可经 settled→candidate 重入补全流程）；已结算 → 不重复记账。
    返 (settlement 摘要, settled_at 时间戳或 None)。

    S038：exit_price_source 由端点层标注并透传——"market"（拉价预填）/
    "manual"（用户手填）/ None（未结算/缺价跳过）。未结算分支也回填该字段。

    S068 R3：R3 的 transition() 已保证同一 (code,date,round) 仅 1 个请求能走到结算
    （并发 holding→settled 在 UPDATE WHERE status=? 处被挡、返 400、到不了此处），
    故维持 S034 原顺序 record→mark_settled——record 抛异常时 settled_at 未落、可重试恢复
    （可恢复优于"先抢占 settled_at 后 record"的不可恢复漏记，见 spec §5 取舍）。
    """
    if state.get("entry_price") is None or state.get("exit_price") is None:
        return {"recorded": False, "reason": "买入价/卖出价缺失未结算；可经 settled→candidate 重入补全流程", "exit_price_source": None}, None
    if state.get("settled_at"):
        return {"recorded": False, "reason": "已结算（不重复记账）", "exit_price_source": None}, None
    summary = _settlement_recorder.record_settlement(state)
    if summary is None:
        return {"recorded": False, "reason": "结算失败（价格缺失）", "exit_price_source": None}, None
    settled_at = datetime.now().isoformat()
    _wf_state_repo.mark_settled(code, date, settled_at)
    return {"recorded": True, **summary, "exit_price_source": exit_price_source}, settled_at


@router.get("/api/workflow/state/{code}")
def get_single_workflow_state(code: str, date: Optional[str] = Query(None, description="日期 YYYY-MM-DD；默认最近交易日")) -> Dict[str, Any]:
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
    # S034 R5：已结算行附结算摘要（entry/exit + 历表 holding/settled 流转 created_at 重算，同 recorder 公式）
    if (
        result.get("settled_at")
        and result.get("entry_price") is not None
        and result.get("exit_price") is not None
    ):
        buy_at, settle_at = _wf_state_repo.get_holding_settle_times(code, d)
        result["settlement"] = _settlement_recorder.settlement_summary(
            result["entry_price"], result["exit_price"],
            buy_at or result["trade_date"],
            settle_at or result["settled_at"],
        )
    return {"data": result}


@router.get("/api/workflow/state/{code}/history")
def get_workflow_state_history(code: str, date: Optional[str] = Query(None, description="日期 YYYY-MM-DD；不传则全部")) -> Dict[str, Any]:
    """S032 R10：某股流转历史（可按日期过滤）。"""
    try:
        history = _wf_state_repo.get_history(code, date)
        return {"data": {"code": code, "date": date, "history": history}}
    except Exception as e:
        raise HTTPException(500, f"获取流转历史失败：{e}") from e


def _normalize_date(date: str) -> str:
    """归一化日期为 YYYY-MM-DD（接受 YYYYMMDD 或 YYYY-MM-DD）。"""
    if "-" in date:
        return date
    if len(date) == 8 and date.isdigit():
        return f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    return date


def _resolve_first_board_date(date: str | None) -> str:
    """解析首板流查询日期——不传 date 时按收盘时点决定取 T 日还是 T-1。

    业务时序：首板流是"T-1 日首板涨停 → T 日建仓"。T 日收盘前（15:00 前）当日
    涨停池为空（当日涨停股要等收盘后才确定），**收盘前应取 T-1 日的选股结果**；
    收盘后（15:00 后）当日涨停池已确定，取当日。

    Args:
        date: YYYY-MM-DD 或 YYYYMMDD 字符串。传了归一化后直接用；None 按收盘时点解析。

    Returns:
        YYYY-MM-DD 字符串（统一格式；不传时 15:00 前返 T-1 交易日，15:00 后返当日）。
    """
    if date:
        return _normalize_date(date)
    from datetime import date as Date, datetime, timedelta

    now = datetime.now()
    today = Date.today()
    # 收盘前（15:00 前）取 T-1（上一个交易日）
    if now.hour < 15:
        from vr_paths import is_trading_day

        t_minus_1 = today - timedelta(days=1)
        # 回溯到交易日（跳过周末/节假日）
        while not is_trading_day(t_minus_1):
            t_minus_1 = t_minus_1 - timedelta(days=1)
        return t_minus_1.isoformat()
    # 收盘后取当日（last_trading_date_str 处理非交易日回退）
    from vr_paths import last_trading_date_str

    return last_trading_date_str()


@router.get("/api/workflow/first-board/candidates")
def get_first_board_candidates(date: str = Query(None, description="交易日 YYYY-MM-DD；不传按收盘时点取T日/T-1")) -> Dict[str, Any]:
    """S075：首板流候选池——返回候选+剔除原因+9维度评分，供前端pipeline展示。

    时序：T 日收盘前（15:00 前）取 T-1 数据（当日涨停池盘前为空），收盘后取当日。
    快照优先：选股只在盘后执行（调度16:15），盘中/盘前读 T-1 盘后快照，不实时跑
    （盘中实时跑会用当日盘中数据污染 T-1 选股结果）。
    诚实标注：9维度评分§44未validated仅参考；阈值/权重待回测校准。
    """
    try:
        from strategies.first_board_filter import run_first_board_filter, load_scores

        target = _resolve_first_board_date(date)
        # date 参数可能是 YYYY-MM-DD，转 YYYYMMDD（em_zt_topic_pool 要 YYYYMMDD）
        compact = target.replace("-", "") if "-" in target else target

        # 快照优先——选股只在盘后执行，盘中/盘前读 T-1 盘后快照
        cached = load_scores(compact)
        if cached:
            candidates = cached.get("scored_candidates", [])
            if len(candidates) > 0:
                # 有数据的快照——还原全部 Pipeline 过程数据
                return {
                    "data": {
                        "date": target,
                        "zt_pool_count": cached.get("zt_pool_count", 0),
                        "first_board_count": cached.get("first_board_count", 0),
                        "candidates": candidates,
                        "excluded": cached.get("excluded", []),
                        "env_flags": cached.get("env_flags", {}),
                        "note": f"历史快照（更新于 {cached['updated_at']}）· 9维度评分§44未validated仅参考",
                        "from_cache": True,
                    }
                }
            # 空快照（盘前跑的，当日涨停池为空）——返回但标注"盘前数据，待盘后更新"
            return {
                "data": {
                    "date": target,
                    "zt_pool_count": cached.get("zt_pool_count", 0),
                    "first_board_count": cached.get("first_board_count", 0),
                    "candidates": [],
                    "excluded": cached.get("excluded", []),
                    "env_flags": cached.get("env_flags", {}),
                    "note": (
                        f"盘前数据（更新于 {cached['updated_at']}），"
                        "盘后16:15调度更新· §44未validated仅参考"
                    ),
                    "from_cache": True,
                }
            }

        # 无快照——盘中/盘前不实时跑（会污染 T-1 数据），收盘后可实时跑
        from datetime import datetime as _dt
        now_hour = _dt.now().hour
        if now_hour < 15:
            # 盘中/盘前无快照：选股只在盘后执行，不实时跑
            return {
                "data": {
                    "date": target,
                    "zt_pool_count": 0,
                    "first_board_count": 0,
                    "candidates": [],
                    "excluded": [],
                    "env_flags": {},
                    "note": (
                        f"T-1（{target}）选股结果未取得，"
                        "选股只在盘后执行（调度16:15），盘中不实时跑避免数据污染· "
                        "§44未validated仅参考"
                    ),
                    "from_cache": False,
                }
            }

        # 收盘后无快照——可实时跑（盘后数据已确定）
        result = run_first_board_filter(compact)
        return {
            "data": {
                "date": target,
                "zt_pool_count": result["zt_pool_count"],
                "first_board_count": result["first_board_count"],
                "candidates": result.get("scored_candidates", result["candidates"]),
                "excluded": result["excluded"],
                "env_flags": result.get("env_flags", {}),
                "note": "9维度评分§44未validated仅参考；阈值/权重待回测校准",
                "from_cache": False,
            }
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"首板流候选查询异常：{e}") from e


@router.get("/api/workflow/first-board/dates")
def get_first_board_dates() -> Dict[str, Any]:
    """S075：首板流可用历史日期列表（有快照的日期，降序，YYYY-MM-DD）。"""
    try:
        from strategies.first_board_filter import list_score_dates
        dates = [_normalize_date(d) for d in list_score_dates()]
        return {"data": {"dates": dates, "count": len(dates)}}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"历史日期查询异常：{e}") from e


__all__ = ["router"]
