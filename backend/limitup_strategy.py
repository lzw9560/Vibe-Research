"""策略逻辑分析引擎 —— 个股策略逻辑匹配 + 风控规则知识展示。

定位：教育性展示，非行动建议。所有文字使用「策略逻辑上」「历史统计特征」等中性表述。
不输出"排板/扫板/回避"等行动建议标签。
"""

from __future__ import annotations

import time
from pydantic import BaseModel

from limitup_screener import (
    DISCLAIMER,
    GENE_HIGH_THRESHOLD,
    GENE_QUALIFY_THRESHOLD,
    LOOKBACK_DAYS,
    GeneScore,
    compute_gene_score,
    get_screener_result,
)
import astock


# ===========================================================================
# 1. 数据结构
# ===========================================================================

class ConditionMatch(BaseModel):
    """单个条件匹配结果（教育性展示）。"""

    condition: str  # 条件名称（如"高封单比"）
    value: str  # 条件值（如"封单比 0.15"）
    description: str  # 策略逻辑说明


class RiskRuleKnowledge(BaseModel):
    """风控规则知识（教育性展示）。"""

    rule_name: str
    description: str
    default_value: str
    configurable: bool
    example: str


class StrategyLogicMatch(BaseModel):
    """策略逻辑条件匹配结果（教育性展示）。"""

    code: str
    name: str
    matches: list[ConditionMatch]
    logic_description: str  # 策略逻辑说明
    disclaimer: str


class LimitUpAnalysis(BaseModel):
    """个股策略分析（客观数据 + 逻辑说明）。"""

    code: str
    name: str
    date: str
    gene_score: GeneScore
    strategy_logic: StrategyLogicMatch
    risk_rules: list[RiskRuleKnowledge]
    backtest_points: list[dict] = []  # 简化版回测数据
    disclaimer: str


# ===========================================================================
# 2. 风控规则知识库（预定义，不动态计算）
# ===========================================================================

RISK_RULES_KNOWLEDGE: list[dict] = [
    {
        "rule_name": "硬性止损",
        "description": "策略逻辑上，亏损达到阈值时止损退出",
        "default_value": "-7%",
        "configurable": True,
        "example": "持仓亏损达到 7% 时，策略逻辑上应止损退出",
    },
    {
        "rule_name": "追踪止损",
        "description": "盈利越多，回撤容忍越小（移动止盈）",
        "default_value": "10档",
        "configurable": True,
        "example": "盈利超过 10% 后，从最高点回撤 3% 即触发追踪止损",
    },
    {
        "rule_name": "时间止损",
        "description": "策略逻辑上，持仓 N 日未盈利则退出",
        "default_value": "3日",
        "example": "持仓 3 个交易日仍未盈利，策略逻辑上应退出观望",
    },
    {
        "rule_name": "5日线止损",
        "description": "策略逻辑上，跌破 5 日均线强制离场",
        "default_value": "跌破MA5",
        "configurable": True,
        "example": "收盘价跌破 5 日均线时，策略逻辑上应离场",
    },
    {
        "rule_name": "单股基准仓位",
        "description": "策略逻辑上的单股基准仓位上限",
        "default_value": "总资产1/6",
        "configurable": True,
        "example": "单只个股持仓不超过总资产的 1/6（约 16.7%）",
    },
    {
        "rule_name": "最大单股仓位",
        "description": "策略逻辑上的单股最大仓位硬顶",
        "default_value": "20%",
        "configurable": True,
        "example": "任何情况下单只个股不超过总资产的 20%",
    },
]


# ===========================================================================
# 3. 条件匹配逻辑
# ===========================================================================

# 封板率阈值
SEAL_RATE_HIGH_THRESHOLD = 60.0


def _build_condition_matches(
    code: str,
    name: str,
    gene: GeneScore,
    pool_item: dict | None = None,
) -> StrategyLogicMatch:
    """根据个股数据和基因得分，生成策略逻辑条件匹配。

    教育性展示：只说"如果满足条件，策略逻辑上会怎样"，不说"你应该怎样"。
    """
    matches: list[ConditionMatch] = []

    # 条件1：高封单比（封单金额 / 成交额 > 0.1）
    if pool_item:
        amount = astock._numf(pool_item.get("amount")) or 0
        # 封单比无法从涨停池直接计算（缺封单量字段），用基因得分中的封板率近似
        seal_rate = gene.factors.get("封板率", 0)
        if seal_rate > SEAL_RATE_HIGH_THRESHOLD:
            matches.append(ConditionMatch(
                condition="高封板率",
                value=f"封板率 {seal_rate:.1f}%",
                description=(
                    f"策略逻辑上，{name} 的封板率为 {seal_rate:.1f}%，"
                    f"属于较高封板率水平。策略逻辑上，高封板率意味着该股的涨停较为稳固。"
                ),
            ))

    # 条件2：基因高分
    if gene.total_score >= GENE_HIGH_THRESHOLD:
        matches.append(ConditionMatch(
            condition="基因高分",
            value=f"基因得分 {gene.total_score}",
            description=(
                f"策略逻辑上，{name} 的基因得分为 {gene.total_score}，"
                f"属于高基因股票。历史统计特征显示，高基因股票在涨停后次日溢价的概率较高。"
            ),
        ))
    elif gene.total_score >= GENE_QUALIFY_THRESHOLD:
        matches.append(ConditionMatch(
            condition="基因合格",
            value=f"基因得分 {gene.total_score}",
            description=(
                f"策略逻辑上，{name} 的基因得分为 {gene.total_score}，"
                f"属于基因合格股票。历史统计特征显示，该类股票具备一定的涨停后溢价能力。"
            ),
        ))
    else:
        matches.append(ConditionMatch(
            condition="基因偏低",
            value=f"基因得分 {gene.total_score}",
            description=(
                f"策略逻辑上，{name} 的基因得分为 {gene.total_score}，"
                f"低于合格阈值。历史统计特征显示，该类股票的涨停后溢价概率相对较低。"
            ),
        ))

    # 条件3：低封板率
    seal_rate = gene.factors.get("封板率", 0)
    if seal_rate < 50:
        matches.append(ConditionMatch(
            condition="低封板率",
            value=f"封板率 {seal_rate:.1f}%",
            description=(
                f"策略逻辑上，{name} 的封板率为 {seal_rate:.1f}%，"
                f"属于较低封板率水平。策略逻辑上，低封板率意味着涨停的稳固性可能不足。"
            ),
        ))

    # 条件4：涨停频次
    freq = gene.factors.get("涨停频次", 0)
    if freq > 60:
        matches.append(ConditionMatch(
            condition="高频涨停",
            value=f"涨停频次得分 {freq:.1f}",
            description=(
                f"策略逻辑上，{name} 在近 {LOOKBACK_DAYS} 日内涨停 {gene.zt_count_250d} 次，"
                f"涨停频次较高。历史统计特征显示，高频涨停股通常受资金关注度高。"
            ),
        ))

    # 条件5：次日溢价率
    premium = gene.factors.get("次日溢价率", 0)
    if premium > 60:
        matches.append(ConditionMatch(
            condition="高次日溢价",
            value=f"次日溢价率 {premium:.1f}%",
            description=(
                f"策略逻辑上，{name} 的次日溢价率为 {premium:.1f}%，"
                f"属于较高的次日溢价水平。历史统计特征显示，该类股票涨停后次日获得正收益的概率较高。"
            ),
        ))

    # 组装逻辑说明
    if matches:
        logic_parts = [m.description for m in matches]
        logic_desc = "；".join(logic_parts) + "。"
    else:
        logic_desc = (
            f"策略逻辑上，{name} 在当前条件下未匹配到明显的策略信号。"
            f"这不代表没有机会，只是基于历史统计特征，该股的因子表现较为中性。"
        )

    return StrategyLogicMatch(
        code=code,
        name=name,
        matches=matches,
        logic_description=logic_desc,
        disclaimer=DISCLAIMER,
    )


# ===========================================================================
# 4. 个股分析主函数
# ===========================================================================

def get_analysis(code: str, date: str | None = None) -> LimitUpAnalysis:
    """获取个股的基因得分 + 策略逻辑匹配 + 风控规则知识。

    流程：
    1. 获取全市场 screener 结果
    2. 从结果中找到该股的基因得分
    3. 对该股单独重新计算 gene_score（含回测数据）
    4. 生成策略逻辑匹配
    5. 返回风控规则知识
    """
    result = get_screener_result(date)

    # 查找该股
    gene = None
    for g in result.gene_scores:
        if g.code == code:
            gene = g
            break

    if gene is None:
        gene_obj = GeneScore(
            code=code,
            name="",
            total_score=0.0,
            factors={
                "次日溢价率": 0.0,
                "红盘率": 0.0,
                "封板率": 0.0,
                "炸板后溢价": 0.0,
                "涨停频次": 0.0,
            },
            wilson_adjusted=0.0,
            qualify=False,
            high_gene=False,
            last_zt_dates=[],
            zt_count_250d=0,
            backtest_points=[],
            backtest_summary={},
        )
    else:
        gene_obj = _rebuild_gene_with_backtest(code, result.date)

    strategy_logic = _build_condition_matches(code, gene_obj.name, gene_obj)

    risk_rules = [
        RiskRuleKnowledge(
            rule_name=r["rule_name"],
            description=r["description"],
            default_value=r.get("default_value", ""),
            configurable=r.get("configurable", False),
            example=r.get("example", ""),
        )
        for r in RISK_RULES_KNOWLEDGE
    ]

    return LimitUpAnalysis(
        code=code,
        name=gene_obj.name,
        date=result.date,
        gene_score=gene_obj,
        strategy_logic=strategy_logic,
        risk_rules=risk_rules,
        backtest_points=gene_obj.backtest_points,
        disclaimer=DISCLAIMER,
    )


# 个股回测缓存
_BT_CACHE: dict = {}
_BT_TTL = 43200  # 12 小时


def _rebuild_gene_with_backtest(code: str, date: str | None) -> GeneScore:
    """重新计算某只股票的 gene_score，包含回测数据。缓存 12 小时。"""
    cache_key = f"bt_{code}_{date or 'today'}"
    now = time.time()
    if cache_key in _BT_CACHE:
        ct, cd = _BT_CACHE[cache_key]
        if now - ct < _BT_TTL:
            return cd

    result = _do_rebuild_gene_with_backtest(code, date)
    _BT_CACHE[cache_key] = (now, result)
    return result


def _do_rebuild_gene_with_backtest(code: str, date: str | None) -> GeneScore:
    """重新计算某只股票的 gene_score，包含回测数据。"""
    from limitup_screener import _resolve_date, _fetch_zt_pool, _collect_zt_history_batch, _compute_factors, _calc_total_score, wilson_lower_bound, LOOKBACK_DAYS, DISCLAIMER

    target_date = _resolve_date(date)
    zt_pool, yzt_pool, zb_pool = _fetch_zt_pool(target_date)

    # 找该股
    stock_item = None
    for item in zt_pool:
        if str(item.get("c", "")) == code:
            stock_item = item
            break

    if stock_item is None:
        return GeneScore(
            code=code, name="", total_score=0.0,
            factors={"次日溢价率": 0.0, "红盘率": 0.0, "封板率": 0.0, "炸板后溢价": 0.0, "涨停频次": 0.0},
            wilson_adjusted=0.0, qualify=False, high_gene=False,
            last_zt_dates=[], zt_count_250d=0, backtest_points=[], backtest_summary={},
        )

    name = stock_item.get("n", "")
    history = _collect_zt_history_batch({code}, target_date, lookback=LOOKBACK_DAYS)
    stock_history = history.get(code, [])
    stock_yzt = [y for y in yzt_pool if str(y.get("c", "")) == code]
    stock_zb = [z for z in zb_pool if str(z.get("c", "")) == code]

    factors = _compute_factors(stock_history, stock_yzt, stock_zb)
    total = _calc_total_score(factors)
    wilson_adj = round(total * wilson_lower_bound(len(stock_history), max(len(stock_history), 1), z=1.96), 2)

    last_dates = sorted(set(
        h.get("_pool_date", "") for h in stock_history if h.get("_pool_date")
    ), reverse=True)[:10]

    # 计算回测数据
    bt_points: list[dict] = []
    if len(stock_history) >= 3:
        history_for_bt: list[dict] = []
        for h in stock_history:
            if len(history_for_bt) >= 2:
                bt_factors = _compute_factors(history_for_bt, [], [])
                bt_total = _calc_total_score(bt_factors)
                lbc = astock._numf(h.get("lbc")) or 0
                bt_points.append({
                    "date": h.get("_pool_date", ""),
                    "gene_score": round(bt_total, 2),
                    "actual_next_day": 1.0 if lbc >= 2 else 0.0,
                })
            history_for_bt.append(h)

    return GeneScore(
        code=code,
        name=name,
        total_score=total,
        factors=factors,
        wilson_adjusted=wilson_adj,
        qualify=total >= GENE_QUALIFY_THRESHOLD,
        high_gene=total >= GENE_HIGH_THRESHOLD,
        last_zt_dates=last_dates,
        zt_count_250d=len(stock_history),
        backtest_points=bt_points,
    )
