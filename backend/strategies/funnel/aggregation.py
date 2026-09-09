# -*- coding: utf-8 -*-
"""聚合 + score_candidates——天气软标注 + 策略分排序 → 候选列表。"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any

from strategies.funnel.registry import (
    STRATEGY_REGISTRY,
    STRATEGIES_BY_FUNNEL_TYPE,
    get_strategy_config,
)
from strategies.funnel.scoring import (
    compute_strategy_score,
    _cand_to_gene,
    _build_market_scan_factors,
)
from strategies.funnel.weather import (
    get_weather_recommendation,
    get_strategies_for_weather,
)
from strategies.strategy_base import (
    StrategyContext,
    StrategyMatchResult,
    _prepare_derived,
    _prepare_pool_item,
)
from strategies.market_scan import _build_market_data  # S094 2b-i-c: market_scan check_quality 闸前移用
from strategies.funnel.quality import (
    check_quality_standards,
    passes_hard_standards,
)

logger = logging.getLogger(__name__)


def _aggregate_strategy_funnels(
    funnel_registry: list,
    cand_match_results: list[tuple[dict, dict[str, StrategyMatchResult]]],
) -> dict[str, dict]:
    """S097 R10：每战法跨候选批次聚合 StrategyFunnelSummary。

    每条件 input_count=评估候选数 / passed_count=hit 数 / data_unavailable_count=数据缺数 /
    pass_rate；candidates 存每候选条件命中标记（hit/miss/data_unavailable 三态）。
    data_ok=False 的战法（无 pattern/DB 等）→ 该候选 conditions 全 data_unavailable，
    独立统计不算逻辑过滤（R7），避免数据缺失误显为「过滤掉 X 只」。
    """
    summaries: dict[str, dict] = {}
    for cfg in funnel_registry:
        cond_specs: list[tuple[str, str, str, str]] = []
        per_cond_hit: dict[str, int] = {}
        per_cond_du: dict[str, int] = {}
        fired_count = 0
        cand_marks: list[dict] = []
        for cand, results_by_code in cand_match_results:
            r = results_by_code.get(cfg.code)
            if r is None:
                cand_marks.append({
                    "code": cand.get("code", ""), "name": cand.get("name", ""),
                    "fired": False, "conditions": [],
                })
                continue
            if not cond_specs:
                cond_specs = [(c.condition_id, c.condition_name, c.factor, c.threshold)
                              for c in r.conditions]
            if r.fired:
                fired_count += 1
            cand_marks.append({
                "code": cand.get("code", ""), "name": cand.get("name", ""),
                "fired": r.fired,
                "conditions": [{"condition_id": c.condition_id, "state": c.state}
                               for c in r.conditions],
            })
            for c in r.conditions:
                if c.state == "hit":
                    per_cond_hit[c.condition_id] = per_cond_hit.get(c.condition_id, 0) + 1
                elif c.state == "data_unavailable":
                    per_cond_du[c.condition_id] = per_cond_du.get(c.condition_id, 0) + 1
        total = len(cand_match_results)
        conditions_agg = []
        for cid, cname, factor, threshold in cond_specs:
            passed = per_cond_hit.get(cid, 0)
            du = per_cond_du.get(cid, 0)
            conditions_agg.append({
                "condition_id": cid, "condition_name": cname,
                "factor": factor, "threshold": threshold,
                "input_count": total, "passed_count": passed,
                "data_unavailable_count": du,
                "pass_rate": round(passed / total, 4) if total else 0.0,
            })
        summaries[cfg.code] = {
            "strategy_code": cfg.code, "strategy_name": cfg.name,
            "fired_count": fired_count, "total_count": total,
            "conditions": conditions_agg, "candidates": cand_marks,
        }
    return summaries


def score_candidates(
    candidates: list[dict],
    weather_state: str | None,
    funnel_type: str,  # S094 R7/T11: 必填 limitup|market_scan（无默认，防 None=全跑 crash，brief 拍板 #3）
    trade_date: str | None = None,
    pool_item_map: dict[str, dict] | None = None,
) -> list[dict]:
    """天气软标注 + 策略分排序 → 候选列表。

    candidates: [{code, name, factors: {seal_rate, premium, ...}, ...}]
    返回：[{code, name, strategy_code, strategy_name, score, breakdown, ...}]

    trade_date: S073 §9.4 游资席位画像接线（可选）；传则 batch 取当日龙虎榜 + per-cand
    compute_seat_risk_factor 修饰策略分（画像未建→modifier 1.0 降级标注）；不传则不接。

    pool_item_map: S086 R7/C8——{code: 涨停池原始 dict（含 fbt/lbc/zdp/p/...）}，
    供调度器构造 StrategyContext.pool_item（storm_reversal 读 fbt；PRD 战法读 lbc/zdp/p）。
    不传（默认 None）→ pool_item=None 降级，storm_reversal/PRD 战法不命中（既有战法不受影响），
    入场价 fallback gene.total_score + "价格代理" 标注（A7）。

    流程（spec §3.1）：
    1. 天气 → 主跑策略组（R3 全 allowed，含暴风雨）+ fallback
    2. 每个候选调 dispatch_match 算命中的战法 signals（match 过滤闭环，无白名单）
    3. 命中战法用其 weight_set 计算策略分
    4. 按策略分降序排序

    grill Q6（match 过滤闭环）：dispatch_match 只返回 match 命中的战法 signals，
    matched_codes 即过滤结果（消灭旧 _MATCHED_STRATEGY_CODES 白名单）。
    """
    # S094 T11：funnel_type 必填——只跑该 funnel_type 的战法（limitup 7 / market_scan 5，不交叉）。
    # R9 行为变化面：limitup 路径不再跑 market_scan 战法（dragon_head/low_absorption/platform_breakout/
    # reverse_package/pattern_reversal 从"可能命中"变"永不命中"——涨停股本不该命中非涨停战法，方向对）。
    if funnel_type not in STRATEGIES_BY_FUNNEL_TYPE:
        return [{
            "strategy_code": "none",
            "note": f"未知 funnel_type={funnel_type}（必填 limitup|market_scan）",
            "strategy_score": 0, "strategy": "无符合条件标的", "factors": {},
        }]
    funnel_codes = set(STRATEGIES_BY_FUNNEL_TYPE[funnel_type])
    funnel_registry = [cfg for cfg in STRATEGY_REGISTRY if cfg.code in funnel_codes]
    primary_codes, _ = get_strategies_for_weather(weather_state)
    primary_codes = [c for c in primary_codes if c in funnel_codes]  # T11: 只本 funnel_type
    # 天气推荐集合（软标注）——用于在候选上标 weather_recommended=True/False
    recommendation = get_weather_recommendation(weather_state)

    # S073 §9.4 游资席位画像接线（batch billboard + profiles；画像未建→load_aggregate_profiles 返空→modifier 1.0 降级）
    # S123 R2.4：切 _meta，partial fetch 标 degraded（live 承重链，不喂残缺数据当完整用）
    seat_profiles = None
    billboard = None
    if trade_date:
        try:
            from strategies.hot_money_seats import (
                compute_seat_risk_factor,
                load_aggregate_profiles,
                fetch_billboard_for_date_meta,
            )
            seat_profiles = load_aggregate_profiles()
            _bb_meta = fetch_billboard_for_date_meta(trade_date)
            if not (_bb_meta["buy_ok"] and _bb_meta["sell_ok"]):
                logging.getLogger(__name__).warning(
                    "score_candidates billboard %s 残缺（buy_ok=%s, sell_ok=%s）"
                    "→ seat risk 用可用 rows 降级",
                    trade_date, _bb_meta["buy_ok"], _bb_meta["sell_ok"],
                )
            billboard = _bb_meta["rows"]
        except Exception:
            seat_profiles = None
            billboard = None

    scored: list[dict] = []
    cand_match_results: list[tuple[dict, dict[str, StrategyMatchResult]]] = []
    for cand in candidates:
        factors = cand.get("factors", {})
        # grill Q6：dict → GeneScore 适配（dispatch_match 的入参类型）
        gene = _cand_to_gene(cand)
        code = cand.get("code", "")
        # S086 R7：从 pool_item_map 构造 ctx.pool_item；derived 走调度器统一 fallback
        pool_item = _prepare_pool_item(pool_item_map, code)
        derived = _prepare_derived(None, code)
        # S094 T10：market_scan 分支构造 market_scan_ctx（4 战法读 PatternScan 始生效，R6）
        market_scan_ctx = None
        if funnel_type == "market_scan":
            _pat = cand.get("pattern")
            market_scan_ctx = {
                "pattern": _pat,
                "sector_rank": cand.get("sector_rank"),
                "rel_strength_vs_sector": getattr(_pat, "relative_strength", None) if _pat is not None else None,
            }
        ctx = StrategyContext(
            code=code, gene=gene, pool_item=pool_item,
            indicators=None, derived=derived, weather_state=weather_state,
            market_scan_ctx=market_scan_ctx,
        )
        # S097：直接调 impl.match 收集全量 StrategyMatchResult（含 fired=False/data_unavailable，
        # 供批次聚合；不经 dispatch_match——后者跳过 fired=False 不够漏斗统计）
        results_by_code: dict[str, StrategyMatchResult] = {}
        for _cfg in funnel_registry:
            try:
                _r = _cfg.strategy_impl.match(ctx)
            except Exception:  # noqa: BLE001 - 单战法异常不阻断
                continue
            if isinstance(_r, StrategyMatchResult):
                results_by_code[_cfg.code] = _r
        cand_match_results.append((cand, results_by_code))
        matched_codes = {c for c, r in results_by_code.items() if r.fired}
        for strat_code in primary_codes:
            cfg = get_strategy_config(strat_code)
            if cfg is None:
                continue
            # S086 R3/C2：暴风雨守卫已删——storm_reversal 可在任意天气评分（若 fbt 命中）
            # grill Q6 match 过滤：仅对 dispatch 命中的战法打分（matched_codes 即过滤结果）
            if strat_code not in matched_codes:
                continue
            # S094 R27: market_scan check_quality 闸前移（硬剔除，不丢 S075 底线）
            if funnel_type == "market_scan":
                market_data = _build_market_data(cand.get("pattern"), cand)
                if not passes_hard_standards(check_quality_standards({"code": code}, strat_code, market_data)):
                    continue
            # S094 audit fix: market_scan 候选无 factors dict（run_non_limitup_funnel 产 pattern 不产 factors）
            # → 从 PatternScan+strat_code 建 per-strategy factors（量能信号 per-strategy R4），否则 score=0.0
            _factors_for_score = _build_market_scan_factors(cand.get("pattern"), cand, strat_code) if funnel_type == "market_scan" else factors
            score, breakdown = compute_strategy_score(_factors_for_score, cfg.weight_set)
            # S073 §9.4 游资画像修饰（画像未建→modifier 1.0 不扣分，标 risk_label）
            seat_risk = None
            if trade_date and billboard is not None:
                try:
                    seat_risk = compute_seat_risk_factor(cand.get("code", ""), trade_date, seat_profiles, None, billboard)
                    score = round(score * seat_risk.score_modifier, 4)
                except Exception:
                    seat_risk = None
            # S097：从 StrategyMatchResult 取 confidence/signal_strength；volume_signal 下沉 match 层
            _r = results_by_code.get(strat_code)
            _confidence = _r.confidence if _r else None
            _signal_strength = int((_r.confidence or 0) * 100) if _r else None
            _volume_signal = cfg.strategy_impl.compute_volume_signal(ctx) if _r else None
            scored.append({
                **{k: v for k, v in cand.items() if k not in ("bars", "pattern")},  # S094 audit: strip heavy bars/pattern（不进 briefing JSON，前端 NonLimitupLane 只用 code/name/sector/strategy_score）
                "strategy_code": cfg.code,
                "strategy_name": cfg.name,
                "strategy_score": score,
                "score_breakdown": breakdown,
                "confidence": _confidence,  # S094 R12: 复用 dispatch_match compute_confidence（不派生 strategy_score/100）
                "signal_strength": _signal_strength,
                "funnel_type": cfg.funnel_type,
                "position_params": dataclasses.asdict(cfg.position_params),
                "weather_recommended": strat_code in recommendation,  # grill Q7：天气推荐标注（软标注）
                "volume_signal": _volume_signal,  # S094 R4：per-strategy 量能信号（None=未计算/涨停 pipeline 降级）
                "hot_money_seat_risk": (
                    {
                        "day_trip_ratio": seat_risk.day_trip_ratio,
                        "relay_ratio": seat_risk.relay_ratio,
                        "risk_label": seat_risk.risk_label,
                        "score_modifier": seat_risk.score_modifier,
                    }
                    if seat_risk else None
                ),
            })

    # S097 R10/R17：批次聚合 StrategyFunnelSummary（每战法跨候选 input/passed/data_unavailable/
    # pass_rate + 候选命中标记），回填 scored 每项 strategy_funnel
    summaries = _aggregate_strategy_funnels(funnel_registry, cand_match_results)
    for s in scored:
        s["strategy_funnel"] = summaries.get(s.get("strategy_code"))

    scored.sort(key=lambda x: x.get("strategy_score", 0), reverse=True)
    if not scored:
        # grill Q5：诚实标注 0 输出原因（不掩盖数据缺失）
        if not candidates:
            note = "当日涨停池无数据"
        elif weather_state == "极端反弹":
            note = "炸板池数据缺失（S055 采集未完成）或昨日无 open_count>=2 的票"
        else:
            note = f"候选股因子值不满足 {', '.join(primary_codes)} 的入场条件"
        return [{
            "strategy_code": "none",
            "note": note,
            "strategy_score": 0,
            "strategy": "无符合条件标的",
            "factors": {},
        }]
    return scored
