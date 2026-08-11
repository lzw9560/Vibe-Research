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
        "entry_type": "尾盘确认反包",
        "stop_loss_pct": -3.0,
        "take_profit_pct": 6.0,
        "max_hold_days": 2,
        "entry_condition": "前日跌停/大阴线+今日放量+游资席位出现",
        "stop_loss_condition": "跌破前日最低价",
        "take_profit_condition": "涨至+5%~+8%后回落",
        "exit_condition": "未出现反包或触发止损/止盈",
        "note": "60日无信号：炸板后溢价因子疑似缺供（S053 查因中）",
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


def match_strategies(code: str, gene: GeneScore, pool_item: dict | None = None) -> list[StrategySignal]:
    """为个股匹配所有适用战法并生成信号（教育性展示）。"""
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
            if gene.factors.get("炸板后溢价", 0) > 0 and gene.factors.get("封板率", 0) >= 50:
                matches.append(ConditionMatch(
                    condition="炸板后回封",
                    value=f"炸板后溢价 {gene.factors.get('炸板后溢价', 0):.1f}%",
                    description=f"策略逻辑上，该股历史统计显示炸板后存在回封概率",
                ))
                confidence = 0.6

        elif strategy["code"] == "low_absorption":
            if gene.total_score >= 65 and gene.factors.get("次日溢价率", 0) > 50:
                matches.append(ConditionMatch(
                    condition="龙头回调+资金关注",
                    value=f"次日溢价率 {gene.factors.get('次日溢价率', 0):.1f}%",
                    description=f"策略逻辑上，该股属于高关注度标的，存在回调低吸机会",
                ))
                confidence = 0.5

        elif strategy["code"] == "reverse_package":
            if gene.factors.get("炸板后溢价", 0) < 0 and gene.total_score >= 55:
                matches.append(ConditionMatch(
                    condition="前日弱势+今日反转",
                    value=f"炸板后溢价 {gene.factors.get('炸板后溢价', 0):.1f}%",
                    description=f"策略逻辑上，该股短期超跌后存在反包概率",
                ))
                confidence = 0.4

        elif strategy["code"] == "n_shape_counterattack":
            if 2 <= gene.zt_count_250d <= 10 and gene.factors.get("涨停频次", 0) > 30:
                matches.append(ConditionMatch(
                    condition="N字形态+放量",
                    value=f"涨停频次 {gene.factors.get('涨停频次', 0):.1f}",
                    description=f"策略逻辑上，该股呈现N字反击的历史统计特征",
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

        if not matches:
            continue

        # 计算入场价/止损/止盈（简化：以当前基因得分作为价格代理）
        entry_price = round(gene.total_score, 2)
        stop_loss = round(entry_price * (1 + strategy["stop_loss_pct"] / 100), 2)
        take_profit = round(entry_price * (1 + strategy["take_profit_pct"] / 100), 2)

        # 历史统计（简化：用基因得分作为成功率代理）
        historical_win_rate = min(confidence * 0.8 + 0.2, 0.95)
        historical_avg_return = round((strategy["take_profit_pct"] - strategy["stop_loss_pct"]) / 2 * historical_win_rate, 2)

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
            ],
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
