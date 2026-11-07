# -*- coding: utf-8 -*-
"""市场情绪评分 — calculate_sentiment_score（132行纯函数，最易测）。

从 feishu_daily_push.py 拆出。为可测性，数据源改为可注入参数：
- 默认参数 None 时走原逻辑（调 CLI 拉数据）
- 测试时直接传入 mock 数据 dict

评分结构（满分100）：
- 量能指标（满分25）
- 涨跌家数/赚钱效应（满分25）
- 连板梯队（满分22）
- 资金流向（满分13）
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))


def _score_volume(total_turnover_yi: float) -> int:
    """量能分项得分（满分25）。total_turnover_yi 为两市成交额（亿元）。"""
    if total_turnover_yi > 15000:
        return 25
    elif total_turnover_yi > 10000:
        return 20
    elif total_turnover_yi > 7000:
        return 15
    else:
        return 5  # 地量=冰点


def _score_effect(up_count: int, down_count: int, limit_down: int) -> int:
    """赚钱效应分项得分（满分25）。"""
    if up_count + down_count > 0:
        up_ratio = up_count / (up_count + down_count)
    else:
        up_ratio = 0.5
    if up_ratio > 0.75 and limit_down < 10:
        return 25
    elif up_ratio > 0.55:
        return 18
    elif up_ratio > 0.45:
        return 12
    else:
        return 5


def _score_ladder(max_boards: int) -> int:
    """连板梯队分项得分（满分22）。"""
    if max_boards >= 7:
        return 22
    elif max_boards >= 5:
        return 18
    elif max_boards >= 3:
        return 12
    elif max_boards >= 2:
        return 8
    else:
        return 3


def _score_flow(total_net_yi: float) -> int:
    """资金流向分项得分（满分13）。total_net_yi 为龙虎榜净买入（亿元）。"""
    if total_net_yi > 5:
        return 13
    elif total_net_yi > 0:
        return 8
    else:
        return 3


def _determine_state(total_score: int) -> tuple[str, dict, str, str, str]:
    """根据总分判定情绪状态。返回 (state, allocation, strategy, wencai, risk)。"""
    if total_score <= 35:
        return (
            "🧊 冰点期",
            {"长线": 70, "中线": 20, "短线": 10},
            "长线红利防御：高股息DRIP+超跌核心资产",
            "股息率大于5%, PB小于1, 央企国企, 非ST, 流通市值大于100亿, 按股息率降序",
            "短线可空仓，长线持有不动",
        )
    elif total_score <= 70:
        return (
            "🔄 震荡期",
            {"长线": 30, "中线": 50, "短线": 20},
            "中线波段轮动：行业动量+小市值Alpha",
            "申万二级行业涨幅前3, 市值50-200亿, 换手率3-8%, MACD金叉, 非ST",
            "破20日线止损中线仓位",
        )
    else:
        return (
            "🔥 沸点期",
            {"长线": 10, "中线": 20, "短线": 70},
            "短线龙头进攻：打板接力+1进2+题材热点",
            "今日涨停, 非ST, 非新股, 换手率5-20%, 所属行业为[当前最热题材], 按市值降序",
            "开盘低开>5%（核按钮）→短线立刻停止接力",
        )


def calculate_sentiment_score(data: dict | None = None) -> dict:
    """计算市场情绪得分（0-100）并返回状态+仓位建议。

    Args:
        data: 可选注入数据，用于测试。结构：
            {
                "indices": [...],          # 指数快照（取 turnover 求和算量能）
                "all_stocks": [...],       # 全市场快照（取 price_change_ratio_pct）
                "ladder": [...],           # 连板天梯（取 board_num 算 max_boards）
                "dragon": [...],           # 龙虎榜（取 net_value 求和算资金）
            }
            None 时走生产逻辑（调 CLI 拉数据）。

    Returns:
        dict: score/state/各分项得分/市场数据/仓位建议/战法/问财指令/风控
    """
    # 数据获取：注入 or 生产
    if data is not None:
        indices = data.get("indices", [])
        all_stocks = data.get("all_stocks", [])
        ladder = data.get("ladder", [])
        dragon = data.get("dragon", [])
    else:
        # 生产环境：调 CLI 拉数据
        from .data import (
            get_index_snapshot,
            get_market_snapshot_all,
            get_limit_up_ladder,
            get_dragon_tiger,
        )
        indices = get_index_snapshot()
        all_stocks = get_market_snapshot_all()
        ladder = get_limit_up_ladder()
        dragon = get_dragon_tiger()

    # 1. 量能指标（30%）
    vol_score = 15  # 默认
    total_turnover = 0
    if indices:
        for idx in indices:
            total_turnover += idx.get("turnover", 0)
        total_yi = total_turnover / 1e8
        vol_score = _score_volume(total_yi)
    else:
        total_yi = 0

    # 2. 涨跌家数（30%）
    up_count = 0
    down_count = 0
    limit_up = 0
    limit_down = 0
    for s in all_stocks:
        chg = s.get("price_change_ratio_pct")
        if chg is None:
            continue
        if chg > 0:
            up_count += 1
        elif chg < 0:
            down_count += 1
        if chg >= 9.5:
            limit_up += 1
        if chg <= -9.5:
            limit_down += 1

    effect_score = _score_effect(up_count, down_count, limit_down)

    # 3. 连板梯队（25%）
    max_boards = 0
    if ladder:
        latest = ladder[0] if ladder else {}
        boards = latest.get("boards", {})
        for level in ["seven_over", "six_board", "five_board", "four_board", "three_board", "two_board"]:
            stocks = boards.get(level, [])
            if stocks:
                for s in stocks:
                    bn = s.get("board_num", 0)
                    if bn > max_boards:
                        max_boards = bn
    ladder_score = _score_ladder(max_boards)

    # 4. 资金流向（15%）— 无北向数据，用龙虎榜净买入近似
    total_net = 0.0
    if dragon:
        total_net = sum(d.get("net_value", 0) or 0 for d in dragon[:10])
    flow_score = _score_flow(total_net / 1e8)

    # 综合得分
    total_score = vol_score + effect_score + ladder_score + flow_score

    # 状态判定
    state, allocation, strategy, wencai, risk = _determine_state(total_score)

    return {
        "score": total_score,
        "state": state,
        "vol_score": vol_score,
        "effect_score": effect_score,
        "ladder_score": ladder_score,
        "flow_score": flow_score,
        "max_boards": max_boards,
        "up_count": up_count,
        "down_count": down_count,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "total_turnover_yi": total_turnover / 1e8 if total_turnover else 0,
        "total_net_yi": total_net / 1e8,
        "allocation": allocation,
        "strategy": strategy,
        "wencai": wencai,
        "risk": risk,
    }
