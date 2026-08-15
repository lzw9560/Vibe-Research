# -*- coding: utf-8 -*-
"""因子注册表（S023）。

因子按 id 注册，工作流/前端按 id 或遍历调用。新因子加注册即可被工作流获得。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from factors.base import FactorResult, SelectionFactor

logger = logging.getLogger(__name__)

_registry: dict[str, SelectionFactor] = {}


def register(factor: SelectionFactor) -> None:
    """注册因子。重复 id 覆盖（开发期灵活）。"""
    _registry[factor.factor_id] = factor
    logger.info("已注册选股因子: %s", factor.factor_id)


def get_factor(factor_id: str) -> SelectionFactor | None:
    """按 id 取因子。"""
    return _registry.get(factor_id)


def get_all_factors() -> list[SelectionFactor]:
    """全部已注册因子。"""
    return list(_registry.values())


def fetch_all(date: str, config: dict[str, Any] | None = None) -> list[FactorResult]:
    """遍历注册表采集所有因子。单个失败不阻塞其他（标 data_status）。"""
    results: list[FactorResult] = []
    for factor in _registry.values():
        try:
            results.append(factor.fetch(date, config))
        except Exception as exc:  # noqa: BLE001 — 单因子失败不阻塞
            logger.warning("因子 %s 采集失败: %s", factor.factor_id, exc)
            results.append(
                FactorResult(
                    factor_id=factor.factor_id,
                    factor_name=getattr(factor, "factor_name", factor.factor_id),
                    candidates=[],
                    layers=[],
                    config={"data_status": "未取得", "reason": str(exc)},
                )
            )
    return results


async def afetch_all(date: str, config: dict[str, Any] | None = None) -> list[FactorResult]:
    """异步并行采集所有因子（S026）。

    每个 factor.fetch 在线程跑（asyncio.to_thread）→ 释放事件循环（health 等端点不被冻）；
    asyncio.gather 并行 → 耗时 ≈ max(各因子) 非 sum。单因子失败不阻塞其他（与 sync 版一致）。
    """
    factors = list(_registry.values())

    async def _one(factor: SelectionFactor) -> FactorResult:
        t0 = time.time()
        try:
            r = await asyncio.to_thread(factor.fetch, date, config)
            logger.info("因子 %s 采集耗时 %.1fs", factor.factor_id, time.time() - t0)
            return r
        except Exception as exc:  # noqa: BLE001 — 单因子失败不阻塞
            logger.warning("因子 %s 采集失败(%.1fs): %s", factor.factor_id, time.time() - t0, exc)
            return FactorResult(
                factor_id=factor.factor_id,
                factor_name=getattr(factor, "factor_name", factor.factor_id),
                candidates=[],
                layers=[],
                config={"data_status": "未取得", "reason": str(exc)},
            )

    return list(await asyncio.gather(*[_one(f) for f in factors]))


_defaults_registered = False


def register_default_factors() -> None:
    """注册内置默认因子。

    默认仅 limitup_screener：candidate_funnel 漏斗层由 _build_funnel_layers
    单一产出（routers/workflow.py），前端 PreMarketBriefing.tsx:246 跳过其因子卡，
    故其因子注册为冗余（grill α，2026-08-16）——漏斗数据不丢（final_candidates/
    funnel_layers 不变），仅去重复表示。详见 memory: quant-mindset-solid-foundation。
    """
    global _defaults_registered
    if _defaults_registered:
        return
    # 延迟导入避免循环依赖
    from factors.limitup_screener_factor import LimitupScreenerFactor

    register(LimitupScreenerFactor())
    _defaults_registered = True
