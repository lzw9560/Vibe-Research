# -*- coding: utf-8 -*-
"""CandidateFunnelFactor — P1 漏斗因子适配层（S023 B1）。

复用 candidate_funnel.run_funnel，包成 FactorResult（原生多层，candidates 带 source_layer/hit_rules）。
合规：只输出客观候选 + 命中规则，不输出买卖方向（参考价位属研究模式 spec）。
"""

from __future__ import annotations

from typing import Any

from candidate_funnel.models import ThresholdConfig
from candidate_funnel import funnel as funnel_mod
from factors.base import Candidate, FactorResult

FACTOR_ID = "candidate_funnel"
FACTOR_NAME = "涨停漏斗（六类指标+活跃度分档）"


class CandidateFunnelFactor:
    """漏斗因子：调 run_funnel，原生多层。"""

    factor_id = FACTOR_ID
    factor_name = FACTOR_NAME

    def fetch(self, date: str, config: dict[str, Any] | None = None) -> FactorResult:
        # 非交易时段转上一交易日（S023 C1）
        from vr_paths import last_trading_date_str
        from datetime import date as _date
        try:
            data_date = last_trading_date_str(_date.fromisoformat(date))
        except (ValueError, TypeError):
            data_date = last_trading_date_str()
        cfg = ThresholdConfig(**(config or {}))
        result = funnel_mod.run_funnel("all", data_date, cfg)

        candidates: list[Candidate] = []
        for card in result.final_candidates:
            hit_rules = list(getattr(card.activity, "rules_applied", []))
            candidates.append(
                Candidate(
                    code=card.code,
                    name=card.name,
                    source_factor_id=FACTOR_ID,
                    source_layer="final",
                    hit_rules=hit_rules,
                    detail={
                        "activity_tier": str(card.activity.tier),
                        "risk_flags": list(card.risk_flags),
                    },
                )
            )

        config_out: dict[str, Any] = {
            "mode": cfg.mode,
            "base": cfg.base.model_dump(),
            "effective": cfg.effective.model_dump() if cfg.effective else None,
            "adjustment": cfg.adjustment,
        }
        if not candidates:
            config_out["data_status"] = "ok"
            config_out["reason"] = "漏斗定稿池无符合标的（非采集失败）"

        return FactorResult(
            factor_id=FACTOR_ID,
            factor_name=FACTOR_NAME,
            candidates=candidates,
            layers=list(result.layers),
            config=config_out,
            as_of=result.as_of.isoformat(),
            data_date=data_date,
        )

    def describe(self) -> dict[str, Any]:
        return {
            "name": FACTOR_NAME,
            "维度": [
                "涨停基因得分（R1）",
                "连板梯队（R1）",
                "全市场活跃度：换手/量比/成交额（R2）",
                "资金流：主力净流/龙虎榜/北向（R2）",
                "集合竞价异动（R3）",
                "公告+板块联动（R3）",
            ],
            "口径": "六类指标 + 活跃度三档（冷/活跃/热），阈值随情绪自适应",
        }
