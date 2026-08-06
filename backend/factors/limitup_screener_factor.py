# -*- coding: utf-8 -*-
"""LimitupScreenerFactor — 旧涨停基因选股因子适配层（S023 B2）。

复用 PreMarketWorkflow（八项标准+战法+仓位），包成 FactorResult（单层+战法/仓位入 detail）。
合规：参考价位（入场/止损/止盈）属研究模式 spec，本因子不输出到候选列表；只放战法名/仓位/置信度/原因。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from datetime import datetime
from typing import Any

from candidate_funnel.models import FunnelLayer
from factors.base import Candidate, FactorResult

FACTOR_ID = "limitup_screener"
FACTOR_NAME = "涨停基因选股（八项标准+战法匹配）"


def _await(coro):
    """在 sync 上下文跑 async PreMarketWorkflow.run。"""
    try:
        asyncio.get_running_loop()
        running = True
    except RuntimeError:
        running = False
    if running:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


class LimitupScreenerFactor:
    """旧因子：调 PreMarketWorkflow，单层包装。candidates 带战法/仓位。"""

    factor_id = FACTOR_ID
    factor_name = FACTOR_NAME

    def fetch(self, date: str, config: dict[str, Any] | None = None) -> FactorResult:
        # 延迟导入避免循环依赖（PreMarketWorkflow 依赖链较重）
        from pre_market_workflow import PreMarketWorkflow

        wf = PreMarketWorkflow(date=date)
        report = _await(wf.run())

        # 构建 candidates（合并 candidates + strong_candidates，去重）
        seen: set[str] = set()
        candidates: list[Candidate] = []
        match_map: dict[str, Any] = {}
        for sm in getattr(report, "strategy_matches", []):
            match_map[sm.code] = sm

        for stock in [*report.strong_candidates, *report.candidates]:
            if stock.code in seen:
                continue
            seen.add(stock.code)
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

        conditions = [
            "基因得分=次日溢价率25%+红盘率25%+封板率25%+炸板后溢价15%+涨停频次10%",
            f"合格阈值≥{GENE_QUALIFY_THRESHOLD}",
            f"高基因≥{GENE_HIGH_THRESHOLD}",
            "战法匹配（8大战法自动匹配）",
            "仓位建议",
        ]

        # 单层包装（旧因子无漏斗分层）
        layer = FunnelLayer(
            layer_id="LS",
            name="涨停基因八项标准",
            as_of=datetime.now(),
            input_count=len(report.candidates) + len(report.strong_candidates),
            output_count=len(candidates),
            filtered_out=[],
            output_codes=[c.code for c in candidates],
            conditions=conditions,
        )

        config_out: dict[str, Any] = {
            "sentiment_index": report.sentiment_index,
            "sentiment_phase": report.sentiment_phase,
        }
        if not candidates:
            # S028 R1：三态区分——warnings(异常/超时) / filtered_out(有数据 0 合格) / 全空(无涨停)
            # scanned = filtered_out + candidates + strong_candidates == gene_scores 总数
            if report.warnings:
                config_out["data_status"] = "未取得"
                config_out["reason"] = "涨停基因选股数据未取得（预计算可能未执行或超时）"
            elif report.filtered_out:
                scanned = len(report.filtered_out) + len(report.candidates) + len(report.strong_candidates)
                config_out["data_status"] = "无合格标的"
                config_out["reason"] = f"今日扫描 {scanned} 只涨停股，均未达合格阈值 {GENE_QUALIFY_THRESHOLD} 分"
                config_out["scanned_count"] = scanned
            else:
                config_out["data_status"] = "未取得"
                config_out["reason"] = "今日无涨停股数据"

        return FactorResult(
            factor_id=FACTOR_ID,
            factor_name=FACTOR_NAME,
            candidates=candidates,
            layers=[layer],
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
