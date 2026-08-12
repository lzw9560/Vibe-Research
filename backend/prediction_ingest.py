# -*- coding: utf-8 -*-
"""S061 R2：预测入账 —— 系统信号自动入册 + 手动录入端点。

系统信号来源（一期）：
- 漏斗 final 候选 → source=funnel_candidate，预测=次日溢价>0
- 战法命中 → source=strategy_hit，预测=按战法 max_hold_days 的止盈/止损

入账幂等：同日同源同股一条（UNIQUE 约束 + OR IGNORE）。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import prediction_ledger as pl

_logger = logging.getLogger("vibe-research")


def ingest_funnel_candidates(date_str: str | None = None,
                              db_path: str = pl.WINRATE_DB_PATH) -> dict[str, Any]:
    """漏斗 final 候选 → 预测入账。

    预测=次日溢价>0，horizon=1（T+1）。
    幂等：重复跑只入一条（UNIQUE(stated_at, source, code)）。
    """
    try:
        from candidate_funnel import funnel as funnel_mod
        from candidate_funnel.models import ThresholdConfig
        from config import AssistantDefaultConfig

        d = AssistantDefaultConfig()
        cfg = ThresholdConfig(mode=d.CANDIDATE_FUNNEL_MODE, base=__import__("candidate_funnel.models", fromlist=["BaseThreshold"]).BaseThreshold(**d.CANDIDATE_FUNNEL_BASE))
    except Exception as exc:
        _logger.warning("[prediction_ingest] 漏斗配置失败: %s", exc)
        return {"ingested": 0, "error": str(exc)}

    target_date = date_str or datetime.now().strftime("%Y-%m-%d")
    try:
        result = funnel_mod.run_funnel("all", target_date, cfg)
    except Exception as exc:
        _logger.warning("[prediction_ingest] 漏斗执行失败: %s", exc)
        return {"ingested": 0, "error": str(exc)}

    ingested = 0
    skipped = 0
    for card in result.final_candidates:
        try:
            p = pl.Prediction(
                stated_at=target_date,
                source="funnel_candidate",
                code=card.code,
                name=card.name,
                signal_ref="funnel:final",
                prediction_type="next_day_premium",
                expected=">0",
                horizon=1,
            )
            new_id = pl.add_prediction(p, db_path=db_path)
            if new_id is not None:
                ingested += 1
            else:
                skipped += 1
        except Exception as exc:
            _logger.warning("[prediction_ingest] %s 入账失败: %s", card.code, exc)
    return {"ingested": ingested, "skipped": skipped, "date": target_date}


def ingest_strategy_hits(date_str: str | None = None,
                          db_path: str = pl.WINRATE_DB_PATH) -> dict[str, Any]:
    """战法命中 → 预测入账。

    用今日 gene_scores 跑战法匹配（match_strategies，sync），命中即入账。
    预测=按战法 max_hold_days 的止盈/止损结果，horizon=max_hold_days。
    """
    try:
        from limitup_strategy import STRATEGY_REGISTRY, match_strategies
        import limitup_screener as ls
    except Exception as exc:
        _logger.warning("[prediction_ingest] 战法模块导入失败: %s", exc)
        return {"ingested": 0, "error": str(exc)}

    target_date = date_str or datetime.now().strftime("%Y-%m-%d")
    try:
        # get_screener_result 是 async，用 asyncio.run 取结果
        import asyncio
        screener_result = asyncio.run(ls.get_screener_result(target_date))
        gene_scores = screener_result.gene_scores if screener_result else []
    except Exception as exc:
        _logger.warning("[prediction_ingest] gene_scores 获取失败: %s", exc)
        return {"ingested": 0, "error": str(exc)}

    strategy_map = {s["code"]: s for s in STRATEGY_REGISTRY}
    ingested = 0
    skipped = 0
    for gene in gene_scores:
        try:
            signals = match_strategies(gene.code, gene)
            for sig in signals:
                strat = strategy_map.get(sig.strategy_code)
                horizon = strat.get("max_hold_days", 1) if strat else 1
                p = pl.Prediction(
                    stated_at=target_date,
                    source="strategy_hit",
                    code=gene.code,
                    name=gene.name,
                    signal_ref=sig.strategy_code,
                    prediction_type="strategy_outcome",
                    expected=sig.take_profit_condition or "止盈",
                    horizon=max(1, int(horizon)),
                )
                new_id = pl.add_prediction(p, db_path=db_path)
                if new_id is not None:
                    ingested += 1
                else:
                    skipped += 1
        except Exception as exc:
            _logger.warning("[prediction_ingest] %s 战法入账失败: %s", gene.code, exc)
    return {"ingested": ingested, "skipped": skipped, "date": target_date}


def ingest_all(date_str: str | None = None,
                db_path: str = pl.WINRATE_DB_PATH) -> dict[str, Any]:
    """盘后调度入口：漏斗 + 战法全量入账。"""
    r1 = ingest_funnel_candidates(date_str, db_path)
    r2 = ingest_strategy_hits(date_str, db_path)
    return {
        "funnel": r1,
        "strategy": r2,
        "total_ingested": r1.get("ingested", 0) + r2.get("ingested", 0),
        "date": date_str or datetime.now().strftime("%Y-%m-%d"),
    }
