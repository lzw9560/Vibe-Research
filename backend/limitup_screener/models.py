# -*- coding: utf-8 -*-
"""limitup_screener 模型与纯计算函数。"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from models.market_snapshot import ZTPoolItem


def _numf(v):
    """东财数值字段可能是 '-'（停牌/无数据）→ 归一成 float 或 None。"""
    return v if isinstance(v, (int, float)) else None


DISCLAIMER = (
    "免责声明：本页面展示的信号和评分基于历史统计特征，不代表未来行为，不构成投资建议。"
    "股市有风险，投资需谨慎。所有分析由用户自己的 AI 给出，Vibe-Research 仅提供数据呈现工具。"
)

LOOKBACK_DAYS = int(os.getenv("LIMITUP_LOOKBACK_DAYS", "252"))
GENE_QUALIFY_THRESHOLD = float(os.getenv("LIMITUP_GENE_QUALIFY_THRESHOLD", "50"))
GENE_HIGH_THRESHOLD = float(os.getenv("LIMITUP_GENE_HIGH_THRESHOLD", "75"))


class GeneScore(BaseModel):
    """单只股票的涨停基因得分（客观数据，非行动建议）。"""

    code: str
    name: str
    total_score: float  # 0-100
    factors: dict[str, float | None]  # 因子得分（百分比形式；K线重建时封板率/炸板后溢价=None）
    wilson_adjusted: float  # Wilson 校正后得分
    qualify: bool  # 是否合格（>= 阈值）
    high_gene: bool  # 高基因（>= 高阈值）
    last_zt_dates: list[str]  # 最近涨停日期
    zt_count_250d: int  # 近 N 日涨停次数
    backtest_points: list[dict] = []  # 简化版回测数据
    backtest_summary: dict = {}  # 轻量级回测统计
    # 封单/流通盘风控（可选，来自涨停池原始数据）
    seal_amount: float = 0.0
    float_shares: float = 0.0
    seal_to_float_ratio: float = 0.0
    limit_up_price: float = 0.0
    limit_down_price: float = 0.0
    # S040 v2: 数据源标注（eastmoney_live=完整5因子 / kline_rebuild=3因子重建）
    data_source: str = "eastmoney_live"
    missing_factors: list[str] = []  # K线重建缺失的因子名（如 ["封板率","炸板后溢价"]）


class ScreenerResult(BaseModel):
    """全市场选股结果（客观数据展示）。"""

    date: str
    gene_scores: list[GeneScore]  # 所有涨停股的基因得分
    qualified: list[GeneScore]  # 基因合格的
    high_gene: list[GeneScore]  # 高基因的
    updated: str  # 更新时间
    disclaimer: str  # 免责声明
    data_freshness: str = "fresh"  # fresh | stale | expired
    data_age_seconds: float = 0.0  # 数据年龄（秒）


@dataclass
class BacktestPoint:
    """单个回测数据点。"""
    date: str          # 涨停日期
    gene_score: float  # 当时计算的基因得分
    actual_next_day: float  # 实际次日表现（连板=1, 未连板=0）
    seal_rate: float   # 封板率因子
    premium_rate: float  # 次日溢价率因子


def wilson_lower_bound(successes: int, trials: int, z: float = 1.96) -> float:
    """Wilson 95% 置信区间下界（小样本自动降置信度）。"""
    if trials == 0:
        return 0.0
    p = successes / trials
    denom = 1 + z ** 2 / trials
    center = (p + z ** 2 / (2 * trials)) / denom
    margin = (z * math.sqrt(p * (1 - p) / trials + z ** 2 / (4 * trials ** 2))) / denom
    return max(0.0, center - margin)


def compute_factors(history: list[ZTPoolItem], yzt: list[ZTPoolItem], zb: list[ZTPoolItem]) -> dict[str, float]:
    """对一只股的历史涨停记录计算五维因子（消费者经 ZTPoolItem 模型读字段）。"""
    n = len(history)
    if n == 0:
        return {
            "次日溢价率": 0.0,
            "红盘率": 0.0,
            "封板率": 0.0,
            "炸板后溢价": 0.0,
            "涨停频次": 0.0,
        }

    # 次日溢价率：连板率（lbc >= 2 的次数 / 总次数）
    lianban_count = sum(1 for h in history if (h.boards or 0) >= 2)
    premium_rate = round(wilson_lower_bound(lianban_count, n) * 100, 2)

    # 红盘率：用 zdp（涨停涨幅）> 0 的比例
    red_count = sum(1 for h in history if (h.limit_pct or 0) > 0)
    red_rate = round(wilson_lower_bound(red_count, n) * 100, 2)

    # 封板率 (25%)：封板强度
    fbt_values = [h.seal_time or 0 for h in history]
    avg_fbt = sum(fbt_values) / len(fbt_values) if fbt_values else 0
    seal_rate = round(max(0.0, min(100.0, (1 - (avg_fbt - 92500) / (145000 - 92500)) * 100)), 2)

    # 炸板后溢价：昨涨停池中有连板记录的占比
    zb_total = len(zb)
    if zb_total > 0:
        yzt_lianban = sum(1 for z in yzt if (z.boards or 0) >= 1)
        rebound_rate = round(wilson_lower_bound(yzt_lianban, zb_total) * 100, 2)
    else:
        rebound_rate = 0.0

    # 涨停频次：归一化
    max_possible = max(LOOKBACK_DAYS // 5, 1)
    freq_score = round(min(n / max_possible, 1.0) * 100, 2)

    return {
        "次日溢价率": premium_rate,
        "红盘率": red_rate,
        "封板率": seal_rate,
        "炸板后溢价": rebound_rate,
        "涨停频次": freq_score,
    }


def calc_total_score(factors: dict[str, float], weights: str = "full") -> float:
    """五维加权合成基因总分。

    weights:
        "full"（默认）: 五维全量——次日溢价率(25%) + 红盘率(25%) + 封板率(25%) + 炸板后溢价(15%) + 涨停频次(10%)
        "rebuild": 三维重建（K 线不可推封板率/炸板后溢价）——次日溢价率(40%) + 红盘率(40%) + 涨停频次(20%)
    """
    w = {
        "full": {"次日溢价率": 0.25, "红盘率": 0.25, "封板率": 0.25, "炸板后溢价": 0.15, "涨停频次": 0.10},
        "rebuild": {"次日溢价率": 0.40, "红盘率": 0.40, "涨停频次": 0.20},
    }.get(weights, {"次日溢价率": 0.25, "红盘率": 0.25, "封板率": 0.25, "炸板后溢价": 0.15, "涨停频次": 0.10})
    total = sum((factors.get(k) or 0.0) * v for k, v in w.items())
    return round(total, 2)


def round_to_tick_size(price: float, tick_size: float = 0.01) -> float:
    """A股 tick-size  rounding（默认 0.01 元）。"""
    return round(round(price / tick_size) * tick_size, 2)


def validate_limit_up_price(prev_close: float, code: str = "") -> tuple[float, float]:
    """计算A股涨跌停价（支持主板/创业板/科创板/ST股）。

    返回 (涨停价, 跌停价)。
    """
    if not prev_close or prev_close <= 0:
        return 0.0, 0.0

    # 创业板/科创板：20%
    if code.startswith(("300", "301", "688", "689")):
        limit = 0.20
    # ST股：5%
    elif "ST" in (code or ""):
        limit = 0.05
    # 主板：10%
    else:
        limit = 0.10

    up = round_to_tick_size(prev_close * (1 + limit))
    down = round_to_tick_size(prev_close * (1 - limit))
    return up, down


def compute_gene_score(
    code: str,
    name: str,
    history: list[ZTPoolItem],
    yzt: list[ZTPoolItem],
    zb: list[ZTPoolItem],
    include_backtest: bool = False,
    pool_item: ZTPoolItem | None = None,
) -> GeneScore:
    """计算单只涨停股的基因得分（消费者经 ZTPoolItem 模型读字段）。"""
    factors = compute_factors(history, yzt, zb)
    total = calc_total_score(factors)
    wilson_adj = round(total * wilson_lower_bound(len(history), max(len(history), 1), z=1.96), 2)

    last_dates = sorted(set(
        h.pool_date for h in history if h.pool_date
    ), reverse=True)[:10]

    # 封单/流通盘 + 涨跌停价（来自涨停池原始数据）
    seal_amount = 0.0
    float_shares = 0.0
    seal_to_float_ratio = 0.0
    limit_up_price = 0.0
    limit_down_price = 0.0
    if pool_item:
        seal_amount = pool_item.seal_amount or 0.0
        float_shares = pool_item.float_shares or 0.0
        seal_to_float_ratio = (seal_amount / float_shares) if float_shares > 0 else 0.0
        prev_close = pool_item.prev_close or 0.0
        if prev_close > 0:
            limit_up_price, limit_down_price = validate_limit_up_price(prev_close, code)

    bt_points: list[dict] = []
    bt_summary: dict = {}
    if include_backtest and len(history) >= 3:
        # 限制回测深度，避免 O(n^2) 计算
        bt_history = history[:10]
        history_for_bt: list[ZTPoolItem] = []
        for h in bt_history:
            if len(history_for_bt) >= 2:
                bt_factors = compute_factors(history_for_bt, [], [])
                bt_total = calc_total_score(bt_factors)
                lbc = h.boards or 0
                bt_points.append({
                    "date": h.pool_date or "",
                    "gene_score": round(bt_total, 2),
                    "actual_next_day": 1.0 if lbc >= 2 else 0.0,
                })
            history_for_bt.append(h)
        lianban_count = sum(1 for p in bt_points if p["actual_next_day"] >= 1)
        total_samples = len(bt_points) if bt_points else 0
        avg_score_lianban = (
            round(sum(p["gene_score"] for p in bt_points if p["actual_next_day"] >= 1) / lianban_count, 1)
            if lianban_count > 0 else None
        )
        bt_summary = {
            "samples": total_samples,
            "lianban_rate": round(lianban_count / total_samples * 100, 1) if total_samples > 0 else 0.0,
            "avg_score_lianban": avg_score_lianban,
        }

    return GeneScore(
        code=code,
        name=name,
        total_score=total,
        factors=factors,
        wilson_adjusted=wilson_adj,
        qualify=total >= GENE_QUALIFY_THRESHOLD,
        high_gene=total >= GENE_HIGH_THRESHOLD,
        last_zt_dates=last_dates,
        zt_count_250d=len(history),
        backtest_points=bt_points,
        backtest_summary=bt_summary,
        seal_amount=seal_amount,
        float_shares=float_shares,
        seal_to_float_ratio=seal_to_float_ratio,
        limit_up_price=limit_up_price,
        limit_down_price=limit_down_price,
    )
