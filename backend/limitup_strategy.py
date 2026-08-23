"""策略逻辑分析引擎 —— 个股策略逻辑匹配 + 风控规则知识展示。

定位：教育性展示，非行动建议。所有文字使用「策略逻辑上」「历史统计特征」等中性表述。
不输出"排板/扫板/回避"等行动建议标签。
"""

from __future__ import annotations

import time
from pydantic import BaseModel
from typing import Any

from limitup_screener import (
    DISCLAIMER,
    GENE_HIGH_THRESHOLD,
    GENE_QUALIFY_THRESHOLD,
    LOOKBACK_DAYS,
    GeneScore,
    compute_gene_score,
    get_screener_result,
)
from risk_models import OneDayRisk
import astock

# S086 涨停战法 pipeline 统一架构：
# - ConditionMatch / match_strategies 来自 strategies.strategy_base（dispatch_match 调度器取代
#   旧 350 行 if/elif switch dispatch；match_strategies 保留为兼容包装，签名不变）
# - STRATEGY_REGISTRY 来自合并后的 strategies.strategy_funnel_registry（单一注册表 12 项）
from strategies.strategy_base import ConditionMatch, match_strategies  # noqa: E402,F401
from strategies.strategy_funnel_registry import STRATEGY_REGISTRY  # noqa: E402,F401


# ===========================================================================
# 0. A股价格校验工具
# ===========================================================================

def _round_to_tick_size(price: float, tick_size: float = 0.01) -> float:
    """A股 tick-size rounding（默认 0.01 元）。"""
    return round(round(price / tick_size) * tick_size, 2)


def _validate_limit_up_price(prev_close: float, code: str = "") -> tuple[float, float]:
    """计算A股涨跌停价（支持主板/创业板/科创板/ST股）。"""
    if not prev_close or prev_close <= 0:
        return 0.0, 0.0
    if code.startswith(("300", "301", "688", "689")):
        limit = 0.20
    elif "ST" in (code or ""):
        limit = 0.05
    else:
        limit = 0.10
    up = _round_to_tick_size(prev_close * (1 + limit))
    down = _round_to_tick_size(prev_close * (1 - limit))
    return up, down


# ===========================================================================
# 1. 数据结构
# ===========================================================================

# ConditionMatch 已上移至 strategies.strategy_base（S086 统一架构，与 StrategySignal.matches 同源）。


class RiskRuleKnowledge(BaseModel):
    """风控规则知识（教育性展示）。"""

    rule_name: str
    description: str
    default_value: str
    configurable: bool
    example: str


class StrategySignal(BaseModel):
    """统一策略信号（替代分散的 AuctionCandidate / StrategyLogicMatch 信号字段）。"""

    code: str
    name: str
    strategy_name: str = ""          # 战法名称
    strategy_code: str = ""          # 首板挖掘/连板接力/炸板回封/低吸龙头/反包战法/N字反击/平台突破/尾盘偷袭
    score: float = 0.0
    signal_strength: int = 0
    confidence: float = 0.0         # 当前信号置信度 (0-1)
    matches: list[ConditionMatch] = []
    logic_description: str = ""
    strategy_tags: list[str] = []
    # 入场逻辑
    entry_price: float = 0.0        # 建议入场价
    entry_condition: str = ""       # 入场确认条件
    entry_type: str = ""            # 入场类型（开盘/竞价/尾盘）
    # 风控逻辑
    stop_loss: float = 0.0          # 止损价
    stop_loss_condition: str = ""   # 止损触发条件
    take_profit: float = 0.0        # 止盈价
    take_profit_condition: str = "" # 止盈触发条件
    # 持仓管理
    max_hold_days: int = 0          # 最大持仓天数
    exit_condition: str = ""        # 主动离场条件
    # 历史统计
    historical_win_rate: float = 0.0   # 历史成功率
    historical_avg_return: float = 0.0 # 历史平均收益率
    sample_size: int = 0            # 统计样本量
    # 综合指标
    risk_reward_ratio: float = 0.0  # 风险收益比
    conditions: dict = {}           # 战法触发条件详情
    # 封单/流通盘风控
    seal_amount: float = 0.0        # 封单额（元）
    float_shares: float = 0.0       # 流通盘（股）
    seal_to_float_ratio: float = 0.0  # 封单/流通盘比
    # 教育性说明
    reasoning: list[str] = []       # 推荐理由（教育性表述）
    risk_notes: list[str] = []      # 风险提示
    # S063 T6：天气适配度（适配/不适配/中性）——calc_weather_fit 填充
    weather_fit: str = "中性"       # 默认中性保证向后兼容（未传 weather_state 时行为不变）
    # S094 R4：per-strategy volume_signal（量能信号）从 match 层下沉注入。
    # 龙头>10亿/平台突破 volume_breakout_ratio>2/低吸>5亿/反包成交额>15亿。
    # None=未计算（涨停 pipeline 不构造 market_scan_ctx，诚实降级）。
    volume_signal: bool | None = None


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
    risk: OneDayRisk | None = None
    risk_rules: list[RiskRuleKnowledge]
    backtest_points: list[dict] = []  # 简化版回测数据
    disclaimer: str
    seal_amount: float = 0.0        # 封单额（元）
    float_shares: float = 0.0       # 流通盘（股）
    seal_to_float_ratio: float = 0.0  # 封单/流通盘比
    limit_up_price: float = 0.0     # 涨停价
    limit_down_price: float = 0.0   # 跌停价


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
) -> StrategyLogicMatch:
    """根据个股数据和基因得分，生成策略逻辑条件匹配。

    教育性展示：只说"如果满足条件，策略逻辑上会怎样"，不说"你应该怎样"。
    """
    matches: list[ConditionMatch] = []

    # 条件1：高封单比（封单金额 / 成交额 > 0.1）
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

    # 绝对封单额/流通盘风控
    if gene.seal_to_float_ratio >= 0.05:
        matches.append(ConditionMatch(
            condition="高封单比",
            value=f"封单/流通盘 {gene.seal_to_float_ratio:.2%}",
            description=(
                f"策略逻辑上，{name} 的封单额占流通盘比例为 {gene.seal_to_float_ratio:.2%}，"
                f"属于较高水平。历史统计特征显示，高封单比通常意味着市场对该股的看多情绪较强。"
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

async def get_analysis(code: str, date: str | None = None, risk: OneDayRisk | None = None) -> LimitUpAnalysis:
    """获取个股的基因得分 + 策略逻辑匹配 + 风控规则知识。

    流程：
      1. 获取全市场 screener 结果
      2. 从结果中找到该股的基因得分
      3. 对该股单独重新计算 gene_score（含回测数据）
      4. 生成策略逻辑匹配
      5. 返回风控规则知识

    risk: 可选的 OneDayRisk 实例。若未提供，则返回 None（前端需处理空值）。
    """
    result = await get_screener_result(date)

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
            date=result.date,
        )
    else:
        gene_obj = await _rebuild_gene_with_backtest(code, result.date)

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
        risk=risk,
        risk_rules=risk_rules,
        backtest_points=gene_obj.backtest_points,
        disclaimer=DISCLAIMER,
        seal_amount=gene_obj.seal_amount,
        float_shares=gene_obj.float_shares,
        seal_to_float_ratio=gene_obj.seal_to_float_ratio,
        limit_up_price=gene_obj.limit_up_price,
        limit_down_price=gene_obj.limit_down_price,
    )


# 个股回测缓存
_BT_CACHE: dict = {}
_BT_TTL = 43200  # 12 小时


async def _rebuild_gene_with_backtest(code: str, date: str | None) -> GeneScore:
    """重新计算某只股票的 gene_score，包含回测数据。缓存 12 小时。"""
    cache_key = f"bt_{code}_{date or 'today'}"
    now = time.time()
    if cache_key in _BT_CACHE:
        ct, cd = _BT_CACHE[cache_key]
        if now - ct < _BT_TTL:
            return cd

    result = await _do_rebuild_gene_with_backtest(code, date)
    _BT_CACHE[cache_key] = (now, result)
    return result


async def _do_rebuild_gene_with_backtest(code: str, date: str | None) -> GeneScore:
    """重新计算某只股票的 gene_score，包含回测数据。"""
    from limitup_screener.service import (
        public_resolve_date,
        public_fetch_zt_pool,
        public_collect_zt_history_batch,
    )
    from limitup_screener.models import (
        compute_factors,
        calc_total_score,
        wilson_lower_bound,
        LOOKBACK_DAYS,
        DISCLAIMER,
    )

    target_date = await public_resolve_date(date)
    zt_pool, yzt_pool, zb_pool = await public_fetch_zt_pool(target_date)

    # 找该股
    stock_item = None
    for item in zt_pool:
        if item.code == code:
            stock_item = item
            break

    if stock_item is None:
        return GeneScore(
            code=code, name="", total_score=0.0,
            factors={"次日溢价率": 0.0, "红盘率": 0.0, "封板率": 0.0, "炸板后溢价": 0.0, "涨停频次": 0.0},
            wilson_adjusted=0.0, qualify=False, high_gene=False,
            last_zt_dates=[], zt_count_250d=0, backtest_points=[], backtest_summary={},
            date=target_date,
        )

    name = stock_item.name or ""
    history = await public_collect_zt_history_batch({code}, target_date, lookback=LOOKBACK_DAYS)
    stock_history = history.get(code, [])
    stock_yzt = [y for y in yzt_pool if y.code == code]
    stock_zb = [z for z in zb_pool if z.code == code]

    factors = compute_factors(stock_history, stock_yzt, stock_zb)
    total = calc_total_score(factors)
    wilson_adj = round(total * wilson_lower_bound(len(stock_history), max(len(stock_history), 1), z=1.96), 2)

    last_dates = sorted(set(
        h.pool_date for h in stock_history if h.pool_date
    ), reverse=True)[:10]

    # 计算回测数据
    bt_points: list[dict] = []
    if len(stock_history) >= 3:
        history_for_bt: list = []
        for h in stock_history:
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
        date=target_date,
    )





# S058：天气适配度软过滤——适配/不适配/中性三态
def calc_weather_fit(strategy_code: str, weather_state: str | None) -> str:
    """战法×天气适配度（软过滤，降权不屏蔽）。

    返回 "适配" / "不适配" / "中性"：
    - weather_state ∈ strategy.weather_regimes → "适配"
    - weather_regimes 非空且不含 weather_state → "不适配"
    - weather_state 为 None/未知 或 regimes 为空 → "中性"（不降权）
    """
    if not weather_state:
        return "中性"
    s = next((s for s in STRATEGY_REGISTRY if s["code"] == strategy_code), None)
    if not s:
        return "中性"
    regimes = s.get("weather_regimes") or []
    if not regimes:
        return "中性"
    if weather_state in regimes:
        return "适配"
    return "不适配"





async def get_strategy_signals(code: str, date: str | None = None) -> list[StrategySignal]:
    """获取个股的八大战法匹配信号。"""
    result = await get_screener_result(date)
    gene = None
    for g in result.gene_scores:
        if g.code == code:
            gene = g
            break

    if gene is None:
        return []

    # 重建含回测数据的 gene_score
    gene_obj = await _rebuild_gene_with_backtest(code, result.date)
    return match_strategies(code, gene_obj)


def get_strategy_registry() -> list[dict]:
    """获取战法库定义（用于前端展示）。

    S058：增 weather_regimes / aliases 字段（天气适配软过滤 + 别名检索）。
    """
    return [
        {
            "code": s["code"],
            "name": s["name"],
            "entry_type": s["entry_type"],
            "entry_condition": s["entry_condition"],
            "stop_loss_condition": s["stop_loss_condition"],
            "take_profit_condition": s["take_profit_condition"],
            "exit_condition": s["exit_condition"],
            "max_hold_days": s["max_hold_days"],
            "weather_regimes": s.get("weather_regimes", []),
            "aliases": s.get("aliases", []),
        }
        for s in STRATEGY_REGISTRY
    ]
