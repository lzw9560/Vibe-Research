# -*- coding: utf-8 -*-
"""S204 T10: early_admission——pre-涨停候选识别（T-1 数据 only，pit guard）。

入池到 tracking_pool（candidate_tracking_pool），不入 workflow_state。escalation_engine
（T11）负责后续 promote（candidate→watching）。

**pit guard**：本函数不主动取数——caller 须传 T-1 及更早数据（盘前 run 时 T 日未开盘，
T-1 收盘是最新可得，天然无 look-ahead）。函数只做 filter，不臆造数据。

pre-涨停候选识别（探索性，社区阈值标 overfit）：
- 板块启动初期：sector zt_count_today 上升（≥2 板块涨停，连板苗子前置）
- 连板苗子：lbc≥1（已 1 板，可能接力）
- gene_score 高（high_gene=1，龙头潜力）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EarlyAdmitCandidate:
    """pre-涨停候选（不可变）。入池到 tracking_pool。"""

    code: str
    admit_date: str  # T-1（pit guard：T 日未开盘，T-1 最新可得）
    signal_type: str  # 'sector_startup'/'relay_seed'/'high_gene'
    indicators_t1: dict[str, Any]  # T-1 收盘指标快照


def scan_early_admission(
    run_date: str,
    candidates: list[dict[str, Any]],
    previous_trade_day: str | None = None,
) -> list[EarlyAdmitCandidate]:
    """识别 pre-涨停候选（T-1 only，pit guard）。

    Args:
        run_date: 盘前 run 日期（T 日，未开盘）。
        candidates: caller 传的 T-1 及更早候选数据 list[dict]，每项含
            code/sector_rank/zt_count_today/lbc/gene_score（as of T-1）。
            **caller 须确保数据 ≤ T-1（本函数不取数，不臆造）**。
        previous_trade_day: T-1 日期（caller 算好传，避免本函数依赖交易日历）。
            None → 用 run_date 减 1 天（简化，caller 须传真实 T-1）。

    Returns:
        list[EarlyAdmitCandidate]——pre-涨停候选（板块启动/连板苗子/high_gene）。
        非 pre-涨停（已涨停/无板块启动）不入池。

    探索性阈值（社区参数标 overfit，须 sensitivity sweep S204 R13）：
    - sector zt_count_today ≥ 2（板块启动，门槛探索性）
    - lbc ≥ 1（连板苗子，已 1 板）
    - high_gene = 1（龙头潜力）
    任一命中 → 入池（signal_type 标识哪个信号触发）。
    """
    admit_date = previous_trade_day or _simple_prev_day(run_date)

    admitted: list[EarlyAdmitCandidate] = []
    for c in candidates:
        code = c.get("code")
        if not code:
            continue
        zt_today = c.get("zt_count_today")
        lbc = c.get("lbc")
        high_gene = c.get("high_gene")
        sector_rank = c.get("sector_rank")
        indicators_t1 = {
            "sector_rank": sector_rank,
            "zt_count_today": zt_today,
            "lbc": lbc,
            "high_gene": high_gene,
        }

        # pre-涨停信号（任一命中入池，signal_type 标识）
        if high_gene == 1:
            admitted.append(EarlyAdmitCandidate(code, admit_date, "high_gene", indicators_t1))
        elif lbc is not None and lbc == 1:
            admitted.append(EarlyAdmitCandidate(code, admit_date, "relay_seed", indicators_t1))
        elif zt_today is not None and zt_today >= 2:
            admitted.append(EarlyAdmitCandidate(code, admit_date, "sector_startup", indicators_t1))
        # 已涨停（lbc>=2 当下涨停）或无信号 → 不入池（pre-涨停 only）

    return admitted


def _simple_prev_day(run_date: str) -> str:
    """简化 T-1（caller 须传真实 previous_trade_day，本函数仅 fallback）。

    不依赖交易日历（避免 early_admission 耦合交易日历模块）——caller 传 previous_trade_day。
    """
    from datetime import datetime, timedelta

    try:
        d = datetime.strptime(run_date, "%Y-%m-%d")
        return (d - timedelta(days=1)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return run_date  # fallback（caller 须传真实 T-1）
