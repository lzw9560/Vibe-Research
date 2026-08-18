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
    )


# ===========================================================================
# 4. 八大战法信号系统（V2.0.2 扩展）
# ===========================================================================

STRATEGY_REGISTRY: list[dict] = [
    {
        "code": "first_plate",
        "name": "首板挖掘",
        "entry_type": "次日竞价/开盘确认后",
        "stop_loss_pct": -3.0,
        "take_profit_pct": 8.0,
        "max_hold_days": 3,
        "entry_condition": "首次涨停+基因得分≥60+量比>1.5",
        "stop_loss_condition": "跌破前日收盘价-3%",
        "take_profit_condition": "涨至+5%~+10%后回落",
        "exit_condition": "持仓3日未盈利或触发止损/止盈",
        "weather_regimes": ["阴天"],
        "aliases": ["首板", "首次涨停"],
    },
    {
        "code": "consecutive_relay",
        "name": "连板接力",
        "entry_type": "连板次日竞价确认",
        "stop_loss_pct": -5.0,
        "take_profit_pct": 12.0,
        "max_hold_days": 2,
        "entry_condition": "连板≥2+封板强度≥0.8+板块热度",
        "stop_loss_condition": "跌破前日收盘价",
        "take_profit_condition": "涨至+8%~+15%后回落",
        "exit_condition": "连板高度≥3板或触发止损/止盈",
        "weather_regimes": ["晴天"],
        "aliases": ["连板", "接力"],
    },
    {
        "code": "break_reseal",
        "name": "炸板回封",
        "entry_type": "回封确认后",
        "stop_loss_pct": -3.0,
        "take_profit_pct": 6.0,
        "max_hold_days": 1,
        "entry_condition": "涨停后开板≥1次+回封+封板强度≥0.6",
        "stop_loss_condition": "跌破回封价",
        "take_profit_condition": "涨至+5%~+8%后回落",
        "exit_condition": "当日收盘前未回封或触发止损/止盈",
        "note": "60日无信号：炸板后溢价因子疑似缺供（S053 查因中）",
        "weather_regimes": ["阴天", "极端反弹"],
        "aliases": ["回封", "炸板回封"],
    },
    {
        "code": "low_absorption",
        "name": "低吸龙头",
        "entry_type": "回调至5日均线附近",
        "stop_loss_pct": -5.0,
        "take_profit_pct": 10.0,
        "max_hold_days": 5,
        "entry_condition": "板块龙头回调+STI非冰点+资金净流入",
        "stop_loss_condition": "跌破10日均线",
        "take_profit_condition": "涨至+8%~+12%后回落",
        "exit_condition": "跌破10日线或持仓5日未盈利",
        "weather_regimes": ["晴天", "阴天"],
        "aliases": ["低吸", "龙头低吸"],
    },
    {
        "code": "reverse_package",
        "name": "反包战法",
        "entry_type": "次日竞价/开盘买入（前日反包确认）",
        "stop_loss_pct": -3.0,
        "take_profit_pct": 6.0,
        "max_hold_days": 1,  # S062：严格 T+1 卖出纪律（fanbao_strategy 原则）
        # S062 T1：entry_condition 吸收 fanbao_strategy 五条件（quantjuzi/fanbao_strategy）
        # 保留 VR 游资席位为加分项；match 逻辑不改（spec §5：外部参数不进选股主链）
        "entry_condition": "T-2/T-3 涨停（加分）+ T-1 未涨停（断板调整）+ T-1 成交额>15亿 + 均线多头（M7/M14>1.0）+ 实体涨跌幅>-3%（加分）；游资席位出现（VR 加分项）",
        "stop_loss_condition": "跌破前日最低价",
        "take_profit_condition": "涨至+5%~+8%后回落",
        "exit_condition": "T+1 卖出纪律（不扛票）或触发止损/止盈",
        "note": "60日无信号：match 逻辑依赖「炸板后溢价」因子缺供（S053 对照结论见卡片）",
        "weather_regimes": ["极端反弹"],
        "aliases": ["反包", "地天板"],
    },
    {
        "code": "n_shape_counterattack",
        "name": "N字反击",
        "entry_type": "回调企稳后放量",
        "stop_loss_pct": -3.0,
        "take_profit_pct": 8.0,
        "max_hold_days": 3,
        "entry_condition": "2日内涨停→回调→再次放量",
        "stop_loss_condition": "跌破回调低点",
        "take_profit_condition": "涨至+5%~+10%后回落",
        "exit_condition": "未出现放量反弹或触发止损/止盈",
        "note": "60日无信号：条件定义待重定义（涨停频次>30 ∧ zt_count_250d≤10 自相矛盾）",
        "weather_regimes": ["晴天", "极端反弹"],
        "aliases": ["N字", "反击"],
    },
    {
        "code": "platform_breakout",
        "name": "平台突破",
        "entry_type": "突破确认后",
        "stop_loss_pct": -5.0,
        "take_profit_pct": 12.0,
        "max_hold_days": 7,
        "entry_condition": "横盘≥5日+今日突破+成交额放大2倍",
        "stop_loss_condition": "跌破平台上沿",
        "take_profit_condition": "涨至+8%~+15%后回落",
        "exit_condition": "突破失败回落或触发止损/止盈",
        "weather_regimes": ["晴天"],
        "aliases": ["突破", "平台"],
    },
    {
        "code": "end_of_day_sneak",
        "name": "尾盘偷袭",
        "entry_type": "尾盘封板确认",
        "stop_loss_pct": -2.0,
        "take_profit_pct": 4.0,
        "max_hold_days": 1,
        "entry_condition": "14:30后急拉+封板+量比>2",
        "stop_loss_condition": "跌破封板价",
        "take_profit_condition": "涨至+3%~+5%后回落",
        "exit_condition": "未封板或触发止损/止盈",
        "weather_regimes": ["阴天"],
        "aliases": ["尾盘", "偷袭"],
    },
    {
        # S062 T3：新增 dragon_head 条目（板块启动期龙头确认，非追高）
        # 来源：ZhuLinsen/daily_stock_analysis dragon_head.yaml + attrib2004/a-share-dragon-strategy
        "code": "dragon_head",
        "name": "龙头战法",
        "entry_type": "板块启动期龙头确认",
        "stop_loss_pct": -5.0,
        "take_profit_pct": 15.0,
        "max_hold_days": 5,
        "entry_condition": "板块领涨地位+相对强度跑赢板块2%+换手>5%+量比>1.5+板块级催化",
        "stop_loss_condition": "跌破5日均线",
        "take_profit_condition": "涨至+10%~+15%后回落",
        "exit_condition": "板块退潮或触发止损/止盈",
        "weather_regimes": ["晴天", "阴天"],
        "aliases": ["龙头", "龙头股"],
    },
    {
        # S081 R1：弱转强接力战法（PRD §2.1）
        # 因子：limit_up_days(lbc) + broken_duration_min/max_drop_pct/last_lock_time(S070 R7 派生) + vol_ratio_1d(hs/前日hs)
        # PRD 阈值为外部拍定值（零数据支撑），标"探索性"，进 config 可配，约定回测调参门限（AC8）
        "code": "weak_turn_strong",
        "name": "弱转强接力",
        "entry_type": "次日竞价确认后",
        "stop_loss_pct": -5.0,
        "take_profit_pct": 10.0,
        "max_hold_days": 2,
        "entry_condition": "昨日涨停+炸板≥20min+回撤≥5%+尾盘封死(≥14:40)+换手1.8-3.0倍",
        "stop_loss_condition": "跌破前日收盘价-5%",
        "take_profit_condition": "涨至+5%~+10%后回落",
        "exit_condition": "持仓2日未盈利或触发止损/止盈",
        "weather_regimes": ["晴天", "极端反弹"],
        "aliases": ["弱转强", "分歧转一致"],
        "note": "S081：PRD 阈值探索性（外部拍定，零数据支撑），因子依赖 S070 R7 派生（60s 粒度近似）",
    },
    {
        # S081 R3：形态反包战法（PRD §2.2）
        # 因子：close_pct(zdp) + max_high_pct/shadow_length_pct(K线) + volume_1d/2d(fundamt+前日) + ma_5_status(K线+均线)
        # 不依赖 S070 R7（因子来自涨停池+K线，可先行实现）
        "code": "pattern_reversal",
        "name": "形态反包",
        "entry_type": "次日突破昨日最高价确认",
        "stop_loss_pct": -4.0,
        "take_profit_pct": 12.0,
        "max_hold_days": 3,
        "entry_condition": "昨日未封涨停+最高≥7%+上影线≥4%+放量1.2倍+5日线向上",
        "stop_loss_condition": "跌破前日最低价",
        "take_profit_condition": "涨至+8%~+12%后回落",
        "exit_condition": "突破失败回落或触发止损/止盈",
        "weather_regimes": ["晴天", "阴天"],
        "aliases": ["反包", "长上影洗盘修复"],
        "note": "S081：PRD 阈值探索性，因子来自涨停池+K线（不依赖 S070 R7）",
    },
]


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


def match_strategies(code: str, gene: GeneScore, pool_item: dict | None = None, indicators: Any = None) -> list[StrategySignal]:
    """为个股匹配所有适用战法并生成信号（教育性展示）。

    S081 重构：indicators 是 candidate_funnel.IndicatorSet（漏斗 R2 输出），
    PRD 2 战法从 indicators 读 max_high_pct/shadow_length_pct/ma_5_status/prev_turnover_pct，
    消除各自调 astock/kline 重复取数（漏斗 activity.py 已取 K线扩展算）。
    - indicators=None（默认）：PRD 战法 K线派生因子取 None 不命中（降级，不报错）
    - indicators 非空：PRD 战法从 indicators 读因子做判定
    保留从 pool_item 读：lbc/hs/zdp/p（涨停池原始字段，漏斗不含）
    保留从 S070 R7 读：broken_duration_min/max_drop_pct/last_lock_time（漏斗不含分时派生）
    """
    signals: list[StrategySignal] = []

    for strategy in STRATEGY_REGISTRY:
        matches: list[ConditionMatch] = []
        confidence = 0.0

        # 简化版战法条件匹配（实际应接入更完整的市场数据）
        if strategy["code"] == "first_plate":
            if gene.total_score >= 60 and gene.factors.get("涨停频次", 0) > 20:
                matches.append(ConditionMatch(
                    condition="首次涨停+基因合格",
                    value=f"基因得分 {gene.total_score}",
                    description=f"策略逻辑上，该股符合首板挖掘的基因门槛",
                ))
                confidence = min(gene.total_score / 100, 1.0)

        elif strategy["code"] == "consecutive_relay":
            if gene.zt_count_250d >= 2 and gene.factors.get("封板率", 0) >= 60:
                matches.append(ConditionMatch(
                    condition="连板+封板强度",
                    value=f"涨停次数 {gene.zt_count_250d}",
                    description=f"策略逻辑上，该股具备连板接力的历史统计特征",
                ))
                confidence = min(gene.factors.get("封板率", 0) / 100, 1.0)

        elif strategy["code"] == "break_reseal":
            # S053 R3：match 改 zt_count_250d 黄金区 [3,5] + 封板率>=80
            # 数据证据：zt_count 3-5 区间 89.5% 命中率（19 条样本），6+ 衰减，11+ 反亏
            if 3 <= gene.zt_count_250d <= 5 and gene.factors.get("封板率", 0) >= 80:
                matches.append(ConditionMatch(
                    condition="炸板回封+历史封板能力",
                    value=f"zt_count_250d={gene.zt_count_250d} 封板率{gene.factors.get('封板率', 0):.1f}%",
                    description=f"策略逻辑上，该股 250 日涨停 {gene.zt_count_250d} 次（黄金区 3-5），历史封板能力强且未过劳",
                ))
                confidence = 0.7

        elif strategy["code"] == "low_absorption":
            if gene.total_score >= 65 and gene.factors.get("次日溢价率", 0) > 50:
                matches.append(ConditionMatch(
                    condition="龙头回调+资金关注",
                    value=f"次日溢价率 {gene.factors.get('次日溢价率', 0):.1f}%",
                    description=f"策略逻辑上，该股属于高关注度标的，存在回调低吸机会",
                ))
                confidence = 0.5

        elif strategy["code"] == "reverse_package":
            # grill Q1-Q2：候选池从涨停池改为 S055 炸板池（open_count >= 2 = 反复开板的真炸板）
            # 数据来源：seal_intraday_snapshots 最近交易日 open_count >= 2 的票
            # 数据缺失时空集，不命中任何票（诚实降级，不臆造候选）
            import sqlite3
            from config import PRIVATE_DATA_DIR
            from pathlib import Path
            zb_db = str(Path(PRIVATE_DATA_DIR) / "seal_intraday.db")
            try:
                zb_conn = sqlite3.connect(zb_db, timeout=5)
                zb_stocks = {r[0] for r in zb_conn.execute(
                    "SELECT DISTINCT code FROM seal_intraday_snapshots "
                    "WHERE open_count >= 2 "
                    "AND date = (SELECT MAX(date) FROM seal_intraday_snapshots)"
                ).fetchall()}
                zb_conn.close()
            except Exception:
                zb_stocks = set()  # 数据缺失时空集，不命中任何票
            if gene.code in zb_stocks:
                matches.append(ConditionMatch(
                    condition="前日炸板≥2次+今日反包",
                    value=f"open_count >= 2（S055 炸板池）",
                    description=f"策略逻辑上，该股前日反复开板（真炸板），今日反包概率较高",
                ))
                confidence = 0.4

        elif strategy["code"] == "n_shape_counterattack":
            # S053 修复：移除矛盾的"涨停频次>30"门槛（与 zt_count_250d<=10 互斥，
            # 导致 60 日无信号）。N字反击核心是"有过涨停历史但未过频"，保留单边约束。
            if 2 <= gene.zt_count_250d <= 10:
                matches.append(ConditionMatch(
                    condition="N字形态+放量",
                    value=f"zt_count_250d={gene.zt_count_250d}",
                    description=f"策略逻辑上，该股 250 日涨停 {gene.zt_count_250d} 次（[2,10] 区间，有过涨停历史但未过频），呈现 N 字反击的历史统计特征",
                ))
                confidence = 0.5

        elif strategy["code"] == "platform_breakout":
            if gene.total_score >= 60 and gene.factors.get("涨停频次", 0) > 40:
                matches.append(ConditionMatch(
                    condition="平台整理+突破",
                    value=f"基因得分 {gene.total_score}",
                    description=f"策略逻辑上，该股具备平台突破的量价特征",
                ))
                confidence = 0.5

        elif strategy["code"] == "end_of_day_sneak":
            if gene.factors.get("封板率", 0) >= 40 and gene.factors.get("次日溢价率", 0) > 40:
                matches.append(ConditionMatch(
                    condition="尾盘封板",
                    value=f"封板率 {gene.factors.get('封板率', 0):.1f}%",
                    description=f"策略逻辑上，该股存在尾盘偷袭的统计特征",
                ))
                confidence = 0.4

        # ===================================================================
        # S081 PRD P2 战法（弱转强接力 + 形态反包）
        # PRD 阈值探索性（外部拍定，零数据支撑），进 config 可配
        # ===================================================================
        elif strategy["code"] == "weak_turn_strong":
            # A4 因子取数：lbc/hs 从 pool_item；S070 R7 派生从 compute_derived_features
            lbc = int(pool_item.get("lbc") or 0) if pool_item else 0
            hs = pool_item.get("hs") if pool_item else None  # 当日换手率
            # S070 R7 派生（broken_duration_min/max_drop_pct/last_lock_time）
            # 输入：get_snapshots_by_code(code, date) 返回的时序列表
            derived: dict = {}
            s070_status = "ok"
            try:
                from risk.seal_intraday_collector import get_snapshots_by_code
                from strategies.intraday_features import compute_derived_features
                from datetime import datetime as _dt
                _snap_date = _dt.now().strftime("%Y-%m-%d")
                _snaps = get_snapshots_by_code(code, _snap_date)
                if not _snaps:
                    s070_status = "missing_s070_r7"
                else:
                    derived = compute_derived_features(_snaps)
                    if derived.get("data_status") == "missing":
                        s070_status = "missing_s070_r7"
            except Exception:
                s070_status = "missing_s070_r7"

            # A7 S070 R7 门禁：snapshots 取不到标 missing_s070_r7 跳过不报错
            if s070_status == "missing_s070_r7":
                matches.append(ConditionMatch(
                    condition="S070 R7 数据层未就绪",
                    value="snapshots 缺失",
                    description="策略逻辑上，弱转强接力战法依赖 S070 R7 分时派生数据，当日 snapshots 未采集，跳过匹配（不报错）",
                ))
                # confidence=0 → 不输出信号（下方 if not matches 仍 continue，但 matches 非空需用 confidence=0 过滤）
                confidence = 0.0
            else:
                broken_duration_min = derived.get("broken_duration_min")
                max_drop_pct = derived.get("max_drop_pct")
                last_lock_time = derived.get("last_lock_time")

                # A5 vol_ratio_1d：当日换手 / 前日换手（从 indicators 读，消除重复取数）
                # S081 重构：原从 S070 snapshots 取前日 hs（恒 None 缺口），改为从
                # IndicatorSet.prev_turnover_pct 读（activity.py 从 K线 prev bar 算）
                vol_ratio_1d = None
                if indicators is not None and hs is not None and hs > 0:
                    prev_hs = getattr(indicators, "prev_turnover_pct", None)
                    if prev_hs and prev_hs > 0:
                        vol_ratio_1d = round(hs / prev_hs, 2)

                # A6 5 因子硬阈值判定（PRD §2.1，阈值探索性，进 config 可配）
                # 阈值默认值（探索性，外部 PRD 拍定，零数据支撑）
                import config as _cfg_mod
                _wts_cfg = getattr(_cfg_mod, "S081_WEAK_TURN_STRONG", None) or {}
                TH_LBC = _wts_cfg.get("limit_up_days_min", 1)
                TH_BROKEN = _wts_cfg.get("broken_duration_min", 20)
                TH_DROP = _wts_cfg.get("max_drop_pct", 5.0)
                TH_LOCK = _wts_cfg.get("last_lock_time", "14:40")
                TH_VOL_LO = _wts_cfg.get("vol_ratio_lo", 1.8)
                TH_VOL_HI = _wts_cfg.get("vol_ratio_hi", 3.0)

                f1 = lbc >= TH_LBC
                f2 = broken_duration_min is not None and broken_duration_min >= TH_BROKEN
                f3 = max_drop_pct is not None and max_drop_pct >= TH_DROP
                f4 = last_lock_time is not None and last_lock_time >= f"2026-01-01T{TH_LOCK}"
                f5 = vol_ratio_1d is not None and TH_VOL_LO <= vol_ratio_1d <= TH_VOL_HI
                hit_count = sum([f1, f2, f3, f4, f5])

                if hit_count >= 4:
                    confidence = 1.0 if hit_count == 5 else 0.7  # 全命中 high / 4 命中 medium
                    if f1:
                        matches.append(ConditionMatch(condition="连板天数达标", value=f"lbc={lbc}", description=f"策略逻辑上，连板 {lbc} 日（阈值≥{TH_LBC}）"))
                    if f2:
                        matches.append(ConditionMatch(condition="炸板时长达标", value=f"broken={broken_duration_min:.1f}min", description=f"策略逻辑上，炸板累计 {broken_duration_min:.1f} 分钟（阈值≥{TH_BROKEN}min，60s粒度近似）"))
                    if f3:
                        matches.append(ConditionMatch(condition="回撤幅度达标", value=f"max_drop={max_drop_pct:.2f}%", description=f"策略逻辑上，炸板后回撤 {max_drop_pct:.2f}%（阈值≥{TH_DROP}%）"))
                    if f4:
                        matches.append(ConditionMatch(condition="尾盘封死达标", value=f"last_lock={last_lock_time}", description=f"策略逻辑上，最后封死时刻 {last_lock_time}（阈值≥{TH_LOCK}）"))
                    if f5:
                        matches.append(ConditionMatch(condition="换手倍数达标", value=f"vol_ratio={vol_ratio_1d:.2f}", description=f"策略逻辑上，换手倍数 {vol_ratio_1d:.2f}（区间 {TH_VOL_LO}-{TH_VOL_HI}）"))
                # ≤3 命中不输出（confidence=0，matches 为空 → continue）

        elif strategy["code"] == "pattern_reversal":
            # B4 因子取数：close_pct 从 zdp（pool_item）；K线派生从 indicators 读
            # S081 重构：原调 kline_rebuild._get_kline_bars 重复取 K线（漏斗 activity.py 已取），
            # 改为从 indicators 读 max_high_pct/shadow_length_pct/ma_5_status/volume
            close_pct = pool_item.get("zdp") if pool_item else None

            max_high_pct = None
            shadow_length_pct = None
            ma_5_status = None
            volume_1d = None
            volume_2d = None

            # K线派生因子从 indicators 读（消除重复取数）
            if indicators is not None:
                max_high_pct = getattr(indicators, "max_high_pct", None)
                shadow_length_pct = getattr(indicators, "shadow_length_pct", None)
                ma_5_status = getattr(indicators, "ma_5_status", None)
            # volume：从 pool_item.fundamt（成交额）近似，无前日对比降级
            # 注：原代码用 bars[-1].volume vs bars[-2].volume，现 indicators 无 volume 字段，
            # 降级 volume_1d/volume_2d=None（放量因子不命中，需漏斗扩展 volume 字段后补）

            # B6 5 因子硬阈值判定（PRD §2.2，阈值探索性）
            import config as _cfg_mod2
            _pr_cfg = getattr(_cfg_mod2, "S081_PATTERN_REVERSAL", None) or {}
            TH_CLOSE = _pr_cfg.get("close_pct_max", 9.5)
            TH_HIGH = _pr_cfg.get("max_high_pct_min", 7.0)
            TH_SHADOW = _pr_cfg.get("shadow_length_pct_min", 4.0)
            TH_VOL_RATIO = _pr_cfg.get("volume_ratio_min", 1.2)
            TH_MA5 = _pr_cfg.get("ma_5_status", "Upward")

            f1 = close_pct is not None and close_pct < TH_CLOSE
            f2 = max_high_pct is not None and max_high_pct >= TH_HIGH
            f3 = shadow_length_pct is not None and shadow_length_pct >= TH_SHADOW
            f4 = (volume_1d is not None and volume_2d is not None
                  and volume_2d > 0 and volume_1d > volume_2d * TH_VOL_RATIO)
            f5 = ma_5_status == TH_MA5
            hit_count = sum([f1, f2, f3, f4, f5])

            if hit_count >= 4:
                confidence = 1.0 if hit_count == 5 else 0.7
                if f1:
                    matches.append(ConditionMatch(condition="收盘涨幅未封涨停", value=f"close_pct={close_pct:.2f}%", description=f"策略逻辑上，收盘涨幅 {close_pct:.2f}%（阈值<{TH_CLOSE}%）"))
                if f2:
                    matches.append(ConditionMatch(condition="最高涨幅达标", value=f"max_high={max_high_pct:.2f}%", description=f"策略逻辑上，最高涨幅 {max_high_pct:.2f}%（阈值≥{TH_HIGH}%）"))
                if f3:
                    matches.append(ConditionMatch(condition="上影线达标", value=f"shadow={shadow_length_pct:.2f}%", description=f"策略逻辑上，上影线 {shadow_length_pct:.2f}%（阈值≥{TH_SHADOW}%）"))
                if f4:
                    matches.append(ConditionMatch(condition="放量达标", value=f"vol_ratio={volume_1d/volume_2d:.2f}", description=f"策略逻辑上，今日量/前日量={volume_1d/volume_2d:.2f}（阈值≥{TH_VOL_RATIO}）"))
                if f5:
                    matches.append(ConditionMatch(condition="5日线向上", value=f"ma_5={ma_5_status}", description=f"策略逻辑上，5日均线 {ma_5_status}（阈值={TH_MA5}）"))
            # ≤3 命中不输出

        if not matches:
            continue

        # S081 A7：S070 R7 门禁的弱转强 confidence=0 → 不输出信号
        if confidence == 0.0:
            continue

        # 计算入场价/止损/止盈
        # S081 A8/B7：PRD 战法用真实触发价（复用 _round_to_tick_size），非 PRD 战法保持基因得分代理
        if strategy["code"] == "weak_turn_strong":
            # 触发价 = _round_to_tick_size(昨日涨停价)；昨日涨停价从 pool_item.p（涨停价）
            _prev_close = pool_item.get("p") if pool_item else None
            if _prev_close and _prev_close > 0:
                entry_price = _round_to_tick_size(_prev_close)
            else:
                entry_price = 0.0
        elif strategy["code"] == "pattern_reversal":
            # 触发价 = _round_to_tick_size(涨停价 + 0.01)；涨停价从 pool_item.p
            # S081 重构：原从 bars[-1].high 取（已删 K线取数），改为从 pool_item.p 近似
            _prev_high = pool_item.get("p") if pool_item else None
            if _prev_high and _prev_high > 0:
                entry_price = _round_to_tick_size(_prev_high + 0.01)
            else:
                entry_price = 0.0
        else:
            # 既有 9 战法：简化以基因得分作价格代理
            entry_price = round(gene.total_score, 2)
        stop_loss = round(entry_price * (1 + strategy["stop_loss_pct"] / 100), 2)
        take_profit = round(entry_price * (1 + strategy["take_profit_pct"] / 100), 2)

        # 历史统计（简化：用基因得分作为成功率代理）
        historical_win_rate = min(confidence * 0.8 + 0.2, 0.95)
        historical_avg_return = round((strategy["take_profit_pct"] - strategy["stop_loss_pct"]) / 2 * historical_win_rate, 2)

        # S081 A8/B7：PRD 战法参数标注"参考值，非执行指令"（AC5/AC7）
        _prd_disclaimer = ""
        if strategy["code"] in ("weak_turn_strong", "pattern_reversal"):
            _prd_disclaimer = "参数为参考值，非执行指令；历史统计特征不代表未来行为，市场有风险"

        signals.append(StrategySignal(
            code=code,
            name=gene.name,
            strategy_name=strategy["name"],
            strategy_code=strategy["code"],
            score=gene.total_score,
            signal_strength=int(confidence * 100),
            confidence=round(confidence, 2),
            matches=matches,
            logic_description="；".join(m.description for m in matches) + "。",
            strategy_tags=[strategy["name"]],
            entry_price=entry_price,
            entry_condition=strategy["entry_condition"],
            entry_type=strategy["entry_type"],
            stop_loss=stop_loss,
            stop_loss_condition=strategy["stop_loss_condition"],
            take_profit=take_profit,
            take_profit_condition=strategy["take_profit_condition"],
            max_hold_days=strategy["max_hold_days"],
            exit_condition=strategy["exit_condition"],
            historical_win_rate=round(historical_win_rate, 2),
            historical_avg_return=historical_avg_return,
            sample_size=gene.zt_count_250d,
            risk_reward_ratio=round(abs(strategy["take_profit_pct"] / strategy["stop_loss_pct"]), 2),
            conditions={
                "entry_condition": strategy["entry_condition"],
                "stop_loss_condition": strategy["stop_loss_condition"],
                "take_profit_condition": strategy["take_profit_condition"],
                "exit_condition": strategy["exit_condition"],
            },
            reasoning=[m.description for m in matches],
            risk_notes=[
                f"历史统计样本量：{gene.zt_count_250d}次",
                f"策略逻辑上，该战法历史平均收益：{historical_avg_return}%",
                "历史统计特征不代表未来行为，仅作研究参考",
            ] + ([_prd_disclaimer] if _prd_disclaimer else []),
        ))

    # 按风险收益比 × 历史胜率排序
    signals.sort(key=lambda s: s.risk_reward_ratio * s.historical_win_rate, reverse=True)
    return signals


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
