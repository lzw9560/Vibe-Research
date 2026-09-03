# -*- coding: utf-8 -*-
"""LimitupScreenerFactor — 旧涨停基因选股因子适配层（S023 B2）。

复用 PreMarketWorkflow（八项标准+战法+仓位），包成 FactorResult（单层+战法/仓位入 detail）。
合规：参考价位（入场/止损/止盈）属研究模式 spec，本因子不输出到候选列表；只放战法名/仓位/置信度/原因。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from candidate_funnel.models import FilterRecord, FunnelLayer
from factors.base import Candidate, FactorResult
from utils.async_utils import run_coro_sync  # C3 缓解：async↔sync 桥接（避嵌套 loop）

FACTOR_ID = "limitup_screener"
FACTOR_NAME = "涨停基因选股（八项标准+战法匹配）"


class LimitupScreenerFactor:
    """旧因子：调 PreMarketWorkflow，单层包装。candidates 带战法/仓位。"""

    factor_id = FACTOR_ID
    factor_name = FACTOR_NAME

    def fetch(self, date: str, config: dict[str, Any] | None = None) -> FactorResult:
        # 延迟导入避免循环依赖（PreMarketWorkflow 依赖链较重）
        from pre_market_workflow import PreMarketWorkflow

        wf = PreMarketWorkflow(date=date)
        report = run_coro_sync(wf.run())

        # 构建 candidates + qualified（合并 strong_candidates + candidates，去重）
        seen: set[str] = set()
        candidates: list[Candidate] = []
        qualified: list[Any] = []  # 去重合并的 GeneScore（L1 output）
        match_map: dict[str, Any] = {}
        ps_by_code: dict[str, Any] = {}
        for sm in getattr(report, "strategy_matches", []):
            match_map[sm.code] = sm
        for ps in getattr(report, "position_suggestions", []):
            ps_by_code[ps.code] = ps

        for stock in [*report.strong_candidates, *report.candidates]:
            if stock.code in seen:
                continue
            seen.add(stock.code)
            qualified.append(stock)
            sm = match_map.get(stock.code)
            detail: dict[str, Any] = {
                "gene_score": getattr(stock, "gene_score", None),
                "is_strong": stock in report.strong_candidates,
            }
            hit_rules = [f"涨停基因得分={getattr(stock, 'gene_score', 0)}"]
            if sm:
                detail["best_strategy"] = sm.best_strategy
                detail["position_pct"] = sm.position_pct
                detail["confidence"] = sm.confidence
                hit_rules.extend(sm.reasons[:3])
                # 参考价位属研究模式 spec，不在此暴露（合规）
            candidates.append(
                Candidate(
                    code=stock.code,
                    name=stock.name,
                    source_factor_id=FACTOR_ID,
                    source_layer="八项标准",
                    hit_rules=hit_rules,
                    detail=detail,
                )
            )

        # 阈值常量 + 五维口径（延迟导入避免循环依赖；limitup_screener 依赖链较重）
        from limitup_screener.models import GENE_HIGH_THRESHOLD, GENE_QUALIFY_THRESHOLD

        scanned = len(report.filtered_out) + len(qualified)

        # ---- S031 R14：因子三层漏斗（打分→战法→仓位），数据全来自 report 既有字段，禁臆造 ----
        # L1 打分
        l1_filtered = [
            FilterRecord(code=f.get("code", ""), name=f.get("name"), reason=f.get("reason", "基因得分未达标"))
            for f in report.filtered_out
        ]
        # S028 三态：仅当无 qualified 时才标 data_status（有合格候选=正常，与 S028 原 if not candidates 一致）
        if qualified:
            l1_status, l1_reason = None, None
        elif report.warnings:
            l1_status, l1_reason = "未取得", "涨停基因选股数据未取得（预计算可能未执行或超时）"
        elif report.filtered_out:
            l1_status, l1_reason = "无合格标的", f"今日扫描 {scanned} 只涨停股，均未达合格阈值 {GENE_QUALIFY_THRESHOLD} 分"
        else:
            l1_status, l1_reason = "未取得", "今日无涨停股数据"

        l1 = FunnelLayer(
            layer_id="LS-1", name="涨停基因打分", as_of=datetime.now(),
            input_count=scanned, output_count=len(qualified),
            filtered_out=l1_filtered,
            output_codes=[g.code for g in qualified],
            conditions=[
                "基因得分=次日溢价率25%+红盘率25%+封板率25%+炸板后溢价15%+涨停频次10%",
                f"合格阈值≥{GENE_QUALIFY_THRESHOLD}",
                f"高基因≥{GENE_HIGH_THRESHOLD}",
                f"扫描 {scanned} 只涨停股",
            ],
            passed=[{"code": g.code, "name": g.name, "gene_score": getattr(g, "total_score", None)} for g in qualified],
            data_status=l1_status, data_reason=l1_reason,
        )

        # L2 战法匹配（passed 携 best_strategy + confidence_value 供 R19 反筛 / R22 合成胜率）
        # 参考价位属研究模式 spec，不在此暴露（合规）
        l2_passed: list[dict[str, Any]] = []
        l2_filtered: list[FilterRecord] = []
        for g in qualified:
            sm = match_map.get(g.code)
            if sm:
                best_signal = sm.matched_strategies[0] if sm.matched_strategies else None
                l2_passed.append({
                    "code": g.code, "name": g.name,
                    "best_strategy": sm.best_strategy,
                    "confidence": sm.confidence,  # 高/中/低 文案
                    "confidence_value": float(best_signal.confidence) if best_signal else 0.0,  # 合成胜率用
                    "reasons": sm.reasons[:3],
                })
            else:
                l2_filtered.append(FilterRecord(code=g.code, name=g.name, reason="未匹配任何战法"))

        l2 = FunnelLayer(
            layer_id="LS-2", name="战法匹配", as_of=datetime.now(),
            input_count=len(qualified), output_count=len(l2_passed),
            filtered_out=l2_filtered,
            output_codes=[p["code"] for p in l2_passed],
            conditions=["8大战法自动匹配", "取置信度最高"],
            passed=l2_passed,
        )

        # L3 仓位建议（input = L2 output；仓位% + 战法 + 置信，不含参考价位）
        l3_passed: list[dict[str, Any]] = []
        l3_filtered: list[FilterRecord] = []
        for p in l2_passed:
            ps = ps_by_code.get(p["code"])
            if ps:
                l3_passed.append({
                    "code": ps.code, "name": ps.name,
                    "suggested_pct": ps.suggested_pct,
                    "confidence": ps.confidence,
                    "matched_strategy": ps.matched_strategy,
                    "reasons": ps.reasons[:3],
                })
            else:
                l3_filtered.append(FilterRecord(code=p["code"], name=p["name"], reason="未给仓位建议"))

        l3 = FunnelLayer(
            layer_id="LS-3", name="仓位建议", as_of=datetime.now(),
            input_count=len(l2_passed), output_count=len(l3_passed),
            filtered_out=l3_filtered,
            output_codes=[p["code"] for p in l3_passed],
            conditions=["仓位建议（PositionAdvisor）"],
            passed=l3_passed,
        )

        config_out: dict[str, Any] = {
            "sentiment_index": report.sentiment_index,
            "sentiment_phase": report.sentiment_phase,
            "scanned_count": scanned,
            # S079 P2 仓位闸 + 龙虎榜风控字段（从 PreMarketReport 透传，供 workflow 响应顶层提取）
            "market_phase": getattr(report, "market_phase", None),
            "market_phase_cap": getattr(report, "market_phase_cap", None),
            "position_cap_tier": getattr(report, "position_cap_tier", None),
            # S096：P2 现象判据（fired_rule + factors，P2RiskPanel 显"为何此 tier"）
            "p2_factors": getattr(report, "p2_factors", None),
            "p2_fired_rule": getattr(report, "p2_fired_rule", None),
            "seat_risk_flags": getattr(report, "seat_risk_flags", None) or {},
            "data_missing_flags": getattr(report, "data_missing_flags", None) or {},
            "execution_checklist": getattr(report, "execution_checklist", None) or [],
            "param_disclaimer": getattr(report, "param_disclaimer", None),
        }

        return FactorResult(
            factor_id=FACTOR_ID,
            factor_name=FACTOR_NAME,
            candidates=candidates,
            layers=[l1, l2, l3],
            config=config_out,
            as_of=report.generated_at,
            data_date=report.date,
        )

    def describe(self) -> dict[str, Any]:
        return {
            "name": FACTOR_NAME,
            "维度": [
                "涨停基因得分（八项标准：连板/封板/换手/量比/资金/题材/龙虎榜/技术位）",
                "战法匹配（8大战法自动匹配）",
                "仓位建议",
            ],
            "口径": "涨停基因得分筛选 + 战法匹配 + 仓位建议；参考价位属研究模式（不在此输出）",
        }
