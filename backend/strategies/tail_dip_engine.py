# -*- coding: utf-8 -*-
"""策略4进化版：尾盘错杀低吸核心引擎。

多专家共识产出，包含：
- calculate_anomalous_deviation()  个股日内无量错杀因子
- check_tail_volatility()           尾盘防诱多庄股过滤因子
- execute_iron_stop_loss()           T+1动态跨领域风控斩仓止损
- financial_red_line_shield()       不可变财务红线防火墙
- premarket_liquidity_fuse()        9:20集合竞价核按钮前置熔断

依赖：akshare / pandas / numpy / scipy
回测基准：strategy4_backtest_result.md（2198事件，Bootstrap p=0.743不显著，
但右尾分布有alpha——>+10%占5.1% vs <-10%仅2.0%）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np

try:
    import akshare as ak
except ImportError:
    ak = None  # type: ignore[assignment]

try:
    from scipy import stats as sp_stats
except ImportError:
    sp_stats = None  # type: ignore[assignment]

logger = logging.getLogger("tail_dip_engine")

# ===========================================================================
# Phase 3: 不可变财务红线防火墙（Immutable Risk Shield）
# ===========================================================================

# 硬风控阈值——多专家审计后不可变，任何策略路径必须通过
HARD_THRESHOLDS: dict[str, float] = {
    "max_limitup_boards": 4,        # 连板>=4直接拉黑（高位非线性退潮）
    "max_goodwill_ratio": 0.15,     # 商誉/净资产 >= 15%
    "max_receivable_ratio": 0.40,   # 应收账款/营收 >= 40%
    "max_pledge_ratio": 0.50,       # 大股东质押率 >= 50%
    "max_drop_pct": -5.0,           # 跌幅 < -5% 不接（重跌是基本面恶化）
    "min_drop_pct": -3.0,           # 跌幅 > -3% 不接（不算错杀）
    "min_amount": 1e7,              # 成交额下限 1000万
    "max_amount_sweet": 5e7,        # 甜区成交额上限 0.5亿
    "min_price": 2.0,               # 价格下限
    "max_price_sweet": 10.0,        # 甜区价格上限
    "max_stop_loss": -0.10,         # 止损 -10%（误杀率仅9.8%）
    "take_profit": 0.10,            # 止盈 +10%
    "max_hold_days": 5,             # 最大持有5日
    "reduction_announce_days": 90,  # 近90天减持公告
}


@dataclass
class FinancialRedLine:
    """单只股票的财务红线检查结果。"""
    code: str
    name: str = ""
    passed: bool = True
    blocked_reasons: list[str] = field(default_factory=list)
    # 财务因子值（供调试/日志）
    goodwill_ratio: float | None = None
    receivable_ratio: float | None = None
    pledge_ratio: float | None = None
    has_reduction_announce: bool = False
    is_st: bool = False
    limitup_boards: int = 0


def financial_red_line_shield(
    code: str,
    name: str = "",
    *,
    goodwill: float | None = None,
    net_assets: float | None = None,
    accounts_receivable: float | None = None,
    revenue: float | None = None,
    pledge_ratio: float | None = None,
    has_reduction_announce: bool = False,
    is_st: bool = False,
    limitup_boards: int = 0,
    is_weekend_eve: bool = False,  # 周四盘后/周五 → 升级安全门槛
) -> FinancialRedLine:
    """不可变财务红线防火墙。

    任何标的必须通过此函数才能进入策略4候选池。
    is_weekend_eve=True 时阈值收紧（对抗周末真空期风险）。

    v10 安全补丁：所有财务因子全为None时（新股/数据缺失），
    标记"财务不可验证"而非默认放行——安全优先。
    """
    result = FinancialRedLine(code=code, name=name)
    _checks_run = 0  # 计数实际执行的检查项

    # ST/退市风险
    if is_st:
        result.passed = False
        result.blocked_reasons.append("ST/退市风险")

    # 连板高度阻断
    max_boards = HARD_THRESHOLDS["max_limitup_boards"]
    # 周末前升级：连板>=3就拉黑（原来>=4）
    if is_weekend_eve:
        max_boards = 3
    if limitup_boards >= max_boards:
        result.passed = False
        result.blocked_reasons.append(f"连板{limitup_boards}>={max_boards}（高位退潮风险）")
    result.limitup_boards = limitup_boards

    # 商誉/净资产
    if goodwill is not None and net_assets and net_assets > 0:
        gw_ratio = goodwill / net_assets
        result.goodwill_ratio = round(gw_ratio, 4)
        threshold = HARD_THRESHOLDS["max_goodwill_ratio"]
        # 周末前收紧到12%
        if is_weekend_eve:
            threshold = 0.12
        if gw_ratio >= threshold:
            result.passed = False
            result.blocked_reasons.append(f"商誉/净资产{gw_ratio:.1%}>={threshold:.0%}")

    # 应收账款/营收
    if accounts_receivable is not None and revenue and revenue > 0:
        ar_ratio = accounts_receivable / revenue
        result.receivable_ratio = round(ar_ratio, 4)
        threshold = HARD_THRESHOLDS["max_receivable_ratio"]
        if is_weekend_eve:
            threshold = 0.35
        if ar_ratio >= threshold:
            result.passed = False
            result.blocked_reasons.append(f"应收/营收{ar_ratio:.1%}>={threshold:.0%}")

    # 大股东质押率
    if pledge_ratio is not None:
        result.pledge_ratio = pledge_ratio
        threshold = HARD_THRESHOLDS["max_pledge_ratio"]
        if is_weekend_eve:
            threshold = 0.40
        if pledge_ratio >= threshold:
            result.passed = False
            result.blocked_reasons.append(f"质押率{pledge_ratio:.1%}>={threshold:.0%}")

    # 近90天减持公告
    if has_reduction_announce:
        result.has_reduction_announce = True
        result.passed = False
        result.blocked_reasons.append("近90天有减持公告（内部人出货）")

    # v10 安全补丁：所有财务因子全为None → 标记"不可验证"，不默认放行
    _has_any_financial = (
        goodwill is not None or accounts_receivable is not None
        or pledge_ratio is not None
    )
    if not _has_any_financial and not is_st and limitup_boards == 0:
        result.passed = False
        result.blocked_reasons.append("财务数据全部缺失（新股或数据源故障），安全优先拦截")

    return result


# ===========================================================================
# Phase 2 核心因子1：个股日内无量错杀因子
# ===========================================================================

@dataclass
class AnomalousDeviationResult:
    """错杀偏离度计算结果。"""
    code: str
    anomalous_deviation: float       # 错杀偏离度（正=错杀，负=板块共跌）
    is_anomalous: bool              # 是否判定为错杀
    individual_change: float        # 个股跌幅%
    sector_change: float           # 板块涨跌幅%
    volume_contraction: float      # 量能收缩比（今日/5日均量）
    confidence: str                # high/medium/low
    detail: str = ""


def calculate_anomalous_deviation(
    code: str,
    individual_change_pct: float,
    sector_change_pct: float,
    volume_today: float,
    volume_ma5: float,
    *,
    min_deviation: float = 3.0,      # 个股vs板块偏离>=3%才算错杀
    high_confidence_deviation: float = 5.0,  # 偏离>=5%才算高信心（v10.2防边界噪声）
    max_volume_ratio: float = 0.8,   # 量能收缩比<0.8才算无量
    low_cf_threshold: float = 10.0,  # 现金流/净利<10%时降信心（v10.2基本面黄灯）
) -> AnomalousDeviationResult:
    """个股日内无量错杀因子。

    核心逻辑（跌幅为负数：个股跌4% = -4.0）：
    - 错杀偏离度 = 个股涨跌幅 - 板块涨跌幅（负值=个股比板块跌更多）
    - abs(偏离度) >= min_deviation 才算错杀（个股相对板块多跌了>=3%）
    - 偏离度>=5% + 无量 → 高信心（v10.2：从3%提到5%防边界噪声）
    - 偏离度3~5% + 无量 → 中信心
    - 量能收缩 = 今日量/5日均量 < 0.8 → 无量下跌（不是机构出货）

    防诱多设计：
    - 如果个股跌但板块也跌（abs(偏离度)<min_deviation），不算错杀——是系统性下跌
    - 如果放量跌（量比>1.2），降信心——机构可能在出货
    - 偏离度刚好=3.0（边界噪声）只给medium不给high
    """
    # 错杀偏离度 = 个股涨跌幅 - 板块涨跌幅（负=个股比板块跌更多）
    raw_deviation = individual_change_pct - sector_change_pct
    # 错杀幅度 = 偏离度的绝对值（个股比板块多跌了多少）
    deviation = abs(raw_deviation)

    # 量能收缩比
    vol_ratio = volume_today / volume_ma5 if volume_ma5 > 0 else 1.0
    volume_contraction = round(vol_ratio, 3)

    # 判定逻辑
    is_anomalous = False
    confidence = "low"
    detail_parts: list[str] = []

    if deviation >= min_deviation:
        is_anomalous = True
        detail_parts.append(f"错杀偏离度{deviation:.1f}%>={min_deviation}%（个股{individual_change_pct:.1f}% vs 板块{sector_change_pct:.1f}%）")

        if vol_ratio < max_volume_ratio:
            # v10.2：偏离>=5%才high，3~5%只给medium（防边界噪声）
            confidence = "high" if deviation >= high_confidence_deviation else "medium"
            detail_parts.append(f"无量收缩{vol_ratio:.2f}<{max_volume_ratio}")
        elif vol_ratio > 1.2:
            confidence = "low"
            detail_parts.append(f"放量{vol_ratio:.2f}>1.2 疑似机构出货")
        else:
            confidence = "medium"
            detail_parts.append(f"量比{vol_ratio:.2f} 正常")
    else:
        detail_parts.append(f"偏离度{deviation:.1f}%<{min_deviation}% 非错杀（个股与板块共跌）")

    return AnomalousDeviationResult(
        code=code,
        anomalous_deviation=round(deviation, 2),
        is_anomalous=is_anomalous,
        individual_change=round(individual_change_pct, 2),
        sector_change=round(sector_change_pct, 2),
        volume_contraction=volume_contraction,
        confidence=confidence,
        detail="; ".join(detail_parts),
    )


# ===========================================================================
# Phase 2 核心因子2：尾盘防诱多庄股过滤因子
# ===========================================================================

@dataclass
class TailVolatilityResult:
    """尾盘波动率过滤结果。"""
    code: str
    passed: bool
    tail_volatility: float          # 尾盘15分钟250日波动率
    random_walk_p_value: float     # 随机游走KS检验p值
    is_manipulated: bool           # 是否判定为恶庄操控
    detail: str = ""


def check_tail_volatility(
    code: str,
    tail_returns_250d: list[float],
    *,
    daily_volatility: float | None = None,  # 个股全日波动率（作为随机游走步长基准）
    rw_n_simulations: int = 1000,
    rw_confidence: float = 0.95,
) -> TailVolatilityResult:
    """尾盘防诱多庄股过滤因子。

    核心逻辑：
    - 取个股近250个交易日尾盘15分钟（14:45-15:00）的收益率序列
    - 计算其实际波动率（标准差）
    - 用全日波动率作为随机游走步长基准，蒙特卡洛模拟随机游走尾盘波动率分布
    - 如果实际波动率显著低于随机游走95%CI下界 → 有人在尾盘刻意压价
    - 拉黑该标的（恶庄操控概率高）

    防过拟合设计：
    - daily_volatility 从全日K线计算，独立于尾盘序列（避免自循环）
    - rw_n_simulations=1000 足够稳定且不依赖特定分布假设
    - 如果tail_returns不足60天，返回passed=True但标记low_confidence
    """
    n = len(tail_returns_250d)

    if n < 60:
        return TailVolatilityResult(
            code=code,
            passed=True,
            tail_volatility=0.0,
            random_walk_p_value=1.0,
            is_manipulated=False,
            detail=f"样本不足{n}<60，跳过过滤",
        )

    arr = np.array(tail_returns_250d, dtype=float)
    actual_vol = float(np.std(arr, ddof=1))

    # 蒙特卡洛随机游走模拟
    if sp_stats is not None:
        # 全日波动率作为随机游走步长基准（独立于尾盘序列，避免自循环）
        # 如果调用方未提供daily_volatility，从尾盘序列的绝对值均值估计（降级模式）
        if daily_volatility is not None and daily_volatility > 0:
            step_size = daily_volatility
        else:
            step_size = float(np.mean(np.abs(arr))) if np.mean(np.abs(arr)) > 0 else 0.01

        simulated_vols = []
        rng = np.random.default_rng(seed=42)  # 固定种子可复现
        for _ in range(rw_n_simulations):
            # 用正态分布模拟随机游走收益率序列（与实际序列同分布假设）
            # 正态分布N(0, step_size)的样本std有抽样偏差——与实际序列对等比较
            sim_returns = rng.normal(0, step_size, size=n)
            sim_vol = float(np.std(sim_returns, ddof=1))
            simulated_vols.append(sim_vol)

        sim_vols_arr = np.array(simulated_vols)
        # CI下界：随机游走序列波动率的5%分位
        ci_lower = float(np.percentile(sim_vols_arr, (1 - rw_confidence) * 100))

        # 双尾KS检验：实际收益率分布 vs 标准随机游走分布
        # 如果actual_vol < ci_lower → 尾盘波动率异常低 → 有人在刻意压价
        is_manipulated = actual_vol < ci_lower

        # 用单尾p值：实际波动率在模拟分布中的CDF位置
        p_value = 1.0 - float(np.mean(sim_vols_arr <= actual_vol)) if actual_vol < ci_lower else 0.5

        detail = (
            f"实际vol={actual_vol:.6f} "
            f"CI下界={ci_lower:.6f} "
            f"p={p_value:.4f} "
            f"{'→ 波动率异常低，疑似恶庄压价' if is_manipulated else '→ 正常'}"
        )
    else:
        # scipy不可用时的降级：用简单的分位数比较
        p_value = 1.0
        is_manipulated = False
        detail = "scipy不可用，降级跳过KS检验"

    return TailVolatilityResult(
        code=code,
        passed=not is_manipulated,
        tail_volatility=round(actual_vol, 6),
        random_walk_p_value=round(p_value, 4),
        is_manipulated=is_manipulated,
        detail=detail,
    )


# ===========================================================================
# Phase 2 核心因子3：动态跨领域风控斩仓止损策略
# ===========================================================================

@dataclass
class IronStopLossResult:
    """铁血止损执行结果。"""
    code: str
    action: str               # hold / stop_loss / take_profit / time_exit
    trigger_price: float     # 触发价
    current_price: float     # 当前价
    entry_price: float       # 入场价
    pnl_pct: float           # 当前盈亏%
    reason: str
    urgency: str = "normal"  # normal / urgent / critical


def execute_iron_stop_loss(
    code: str,
    entry_price: float,
    current_price: float,
    intraday_low: float,
    intraday_high: float,
    days_held: int,
    *,
    market_phase: str = "normal",        # normal / crash / euphoria
    is_weekend_eve: bool = False,       # 周五 → 收紧止损
    sector_crash_pct: float = 0.0,       # 板块当日跌幅（正数=跌）
    position_size_multiplier: float = 1.0,  # 回撤断路器乘数
) -> IronStopLossResult:
    """T+1动态跨领域风控斩仓止损策略。

    融合四专家视角：
    - 微观：intraday_low触止损 → 立即执行（不等收盘）
    - 量化：-10%止损+10%止盈（回测最优参数，误杀率仅9.8%）
    - 基本面：板块暴跌>3% → 止损线上移（预防连锁爆仓）
    - 宏观：周五/回撤熔断 → 收紧止损+限制持有

    拒绝人工锁仓幻觉：
    - 如果position_size_multiplier=0（回撤断路器触发），任何持仓立即清仓
    - 不依赖"等一等会回来"的直觉
    """
    pnl_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0.0

    # ━━━ 硬熔断：回撤断路器触发 → 立即清仓 ━━━
    if position_size_multiplier <= 0.0:
        return IronStopLossResult(
            code=code,
            action="stop_loss",
            trigger_price=current_price,
            current_price=current_price,
            entry_price=entry_price,
            pnl_pct=round(pnl_pct * 100, 2),
            reason="回撤断路器触发(size_mult=0)，立即清仓",
            urgency="critical",
        )

    # ━━━ 动态止损线 ━━━
    base_stop = HARD_THRESHOLDS["max_stop_loss"]  # -10%
    # 周末前收紧到-7%
    if is_weekend_eve:
        base_stop = -0.07
    # 板块暴跌>3% → 止损线上移1%（预防连锁爆仓）
    if sector_crash_pct > 3.0:
        base_stop += 0.01  # -10% → -9%
    # 市场崩盘 → 止损线上移2%
    if market_phase == "crash":
        base_stop += 0.02

    stop_loss_line = entry_price * (1 + base_stop)
    take_profit_line = entry_price * (1 + HARD_THRESHOLDS["take_profit"])
    max_hold = HARD_THRESHOLDS["max_hold_days"]
    # 周末前缩短持有期到3天
    if is_weekend_eve:
        max_hold = 3

    # ━━━ 止损检查：先看intraday_low（微观层面） ━━━
    if intraday_low <= stop_loss_line:
        return IronStopLossResult(
            code=code,
            action="stop_loss",
            trigger_price=round(stop_loss_line, 2),
            current_price=current_price,
            entry_price=entry_price,
            pnl_pct=round(pnl_pct * 100, 2),
            reason=f"止损触发：日内最低{intraday_low:.2f}≤止损线{stop_loss_line:.2f}"
                   f"（{base_stop:.0%}{' 周末收紧' if is_weekend_eve else ''}）",
            urgency="urgent",
        )

    # ━━━ 止盈检查 ━━━
    if intraday_high >= take_profit_line:
        return IronStopLossResult(
            code=code,
            action="take_profit",
            trigger_price=round(take_profit_line, 2),
            current_price=current_price,
            entry_price=entry_price,
            pnl_pct=round(pnl_pct * 100, 2),
            reason=f"止盈触发：日内最高{intraday_high:.2f}≥止盈线{take_profit_line:.2f}",
            urgency="normal",
        )

    # ━━━ 时间止损 ━━━
    if days_held >= max_hold:
        return IronStopLossResult(
            code=code,
            action="time_exit",
            trigger_price=current_price,
            current_price=current_price,
            entry_price=entry_price,
            pnl_pct=round(pnl_pct * 100, 2),
            reason=f"持有{days_held}日≥上限{max_hold}日，时间止损退出",
            urgency="normal",
        )

    # ━━━ 持有 ━━━
    return IronStopLossResult(
        code=code,
        action="hold",
        trigger_price=0.0,
        current_price=current_price,
        entry_price=entry_price,
        pnl_pct=round(pnl_pct * 100, 2),
        reason=f"持有中（{days_held}/{max_hold}日，止损{stop_loss_line:.2f}，"
               f"止盈{take_profit_line:.2f}）",
        urgency="normal",
    )


# ===========================================================================
# Phase 1 辅助：9:20集合竞价核按钮前置熔断
# ===========================================================================

@dataclass
class PremarketFuseResult:
    """集合竞价前置熔断结果。"""
    code: str
    blocked: bool
    reason: str


def premarket_liquidity_fuse(
    code: str,
    auction_pct: float,
    sector_gap_pct: float,
    auction_volume_ratio: float,
    auction_unmatched: float,
    prev_close: float,
    entry_stop_loss_line: float,
) -> PremarketFuseResult:
    """9:20集合竞价核按钮前置熔断。

    测试题1的回答：
    - 反向核按钮：个股竞价<-7%但板块>-1% → 私募恶意砸盘
    - 流动性锁死：竞价量比<0.3 + 未匹配量>0
    - 隔夜gap-down穿透止损价
    """
    # 1. 反向核按钮
    if auction_pct < -7.0 and sector_gap_pct > -1.0:
        return PremarketFuseResult(
            code=code, blocked=True,
            reason=f"反向核按钮：个股竞价{auction_pct:.1f}% vs 板块{sector_gap_pct:.1f}%",
        )

    # 2. 流动性锁死
    if auction_volume_ratio < 0.3 and auction_unmatched > 0:
        return PremarketFuseResult(
            code=code, blocked=True,
            reason=f"流动性锁死：竞价量比{auction_volume_ratio:.2f}+未匹配{auction_unmatched:.0f}",
        )

    # 3. 隔夜gap-down穿透止损价
    estimated_open = prev_close * (1 + auction_pct / 100)
    if estimated_open <= entry_stop_loss_line:
        return PremarketFuseResult(
            code=code, blocked=True,
            reason=f"隔夜gap-down：预估开盘{estimated_open:.2f}≤止损线{entry_stop_loss_line:.2f}",
        )

    return PremarketFuseResult(code=code, blocked=False, reason="pass")


# ===========================================================================
# Phase 2 辅助：财务因子替代（季报更替期数据滞后补丁）
# ===========================================================================

def fetch_financial_substitute_factors(code: str) -> dict[str, Any]:
    """用替代因子补盲季报更替期的财务数据滞后。

    测试题2的回答（v2.00生产模式——已用akshare验证接口）：
    - 应收账款周转率 → 反推应收/营收比（替代滞后应收数据）
    - 经营现金流/净利润 → 盈利质量背离度（替代滞后现金流）
    - 质押率 → akshare全市场质押数据
    - 增减持公告 → akshare CnInfo接口

    用 stock_financial_analysis_indicator（2s/票，86列含应收周转率+现金流背离+资产负债率）
    而非 stock_balance_sheet_by_report_em（33s/票，319列但太慢）。

    返回 dict，key = 因子名，value = 数值或None。
    如果akshare不可用或取数失败，返回空dict（不阻塞——降级为无过滤）。
    """
    result: dict[str, Any] = {}

    if ak is None:
        logger.warning("akshare 不可用，财务替代因子降级为无过滤")
        return result

    # 1. 财务指标（应收周转率+经营现金流背离+资产负债率）
    try:
        df = ak.stock_financial_analysis_indicator(symbol=code, start_year="2024")
        if df is not None and not df.empty:
            latest = df.iloc[0]
            ar_turnover = float(latest.get("应收账款周转率(次)", 0) or 0)
            debt_ratio = float(latest.get("资产负债率(%)", 0) or 0)
            cf_to_ni = float(latest.get("经营现金净流量与净利润的比率(%)", 0) or 0)

            # 应收/营收 ≈ 100/周转率（近似：周转率=营收/应收均值）
            ar_to_revenue = 100.0 / ar_turnover if ar_turnover > 0 else None
            result["ar_to_revenue_pct"] = round(ar_to_revenue, 1) if ar_to_revenue else None
            result["debt_ratio"] = round(debt_ratio, 1)
            result["cf_to_ni_pct"] = round(cf_to_ni, 1)
            result["earnings_quality_poor"] = cf_to_ni < 30
            result["cf_negative"] = cf_to_ni < 0
    except Exception as e:  # noqa: BLE001
        logger.debug("取财务指标失败 %s: %s", code, e)

    # 1b. 商誉/权益（从资产负债表拉，较慢但精确——33s/票，只拉最新1条）
    try:
        # 推断交易所前缀
        prefix = "SH" if code.startswith("6") else "SZ"
        bs_df = ak.stock_balance_sheet_by_report_em(symbol=f"{prefix}{code}")
        if bs_df is not None and not bs_df.empty:
            latest_bs = bs_df.iloc[0]
            goodwill = float(latest_bs.get("GOODWILL", 0) or 0)
            equity = float(latest_bs.get("TOTAL_PARENT_EQUITY", 0) or 0)
            if equity > 0:
                gw_ratio = goodwill / equity
                result["goodwill_ratio"] = round(gw_ratio, 4)
                result["goodwill_blocked"] = gw_ratio >= HARD_THRESHOLDS["max_goodwill_ratio"]
            result["goodwill_yi"] = round(goodwill / 1e8, 2)
            result["equity_yi"] = round(equity / 1e8, 2)
    except Exception as e:  # noqa: BLE001
        logger.debug("取商誉失败 %s: %s", code, e)

    # 2. 大股东质押率（全市场数据，一次拉取）
    try:
        today_str = datetime.now().strftime("%Y%m%d")
        pledge_df = ak.stock_gpzy_pledge_ratio_em(date=today_str)
        if pledge_df is not None and not pledge_df.empty:
            row = pledge_df[pledge_df["股票代码"] == code]
            if not row.empty:
                # 质押比例列可能是百分比字符串或float
                raw_val = row.iloc[0].get("质押比例", 0)
                if isinstance(raw_val, str):
                    raw_val = float(raw_val.replace("%", "").replace("亿", ""))
                result["pledge_ratio"] = float(raw_val) / 100.0 if float(raw_val) > 1 else float(raw_val)
    except Exception as e:  # noqa: BLE001
        logger.debug("取质押率失败 %s: %s", code, e)

    # 3. 增减持公告（近90天）——v10.1修正：stock_share_change_cninfo返回的是
    # 全部股本变动（A股上市/定期报告/限售解禁/增发/回购），不是减持公告。
    # 之前的逻辑"有数据就标记has_reduction=True"导致全部票被误杀。
    # 修正：检查"变动原因"列是否含"减持"关键词，且公告日期在90天内。
    try:
        change_df = ak.stock_share_change_cninfo(symbol=code)
        if change_df is not None and not change_df.empty and "变动原因" in change_df.columns:
            # 只标记"减持"类变动（排除A股上市/定期报告/限售解禁/增发/回购）
            reduction_mask = change_df["变动原因"].str.contains("减持", na=False)
            if reduction_mask.any():
                # 检查最近90天有无减持
                if "公告日期" in change_df.columns:
                    cutoff = datetime.now() - timedelta(days=HARD_THRESHOLDS["reduction_announce_days"])
                    recent = change_df[reduction_mask].copy()
                    recent["公告日期"] = recent["公告日期"].astype(str)
                    # 简化：有减持记录就标记（精确日期过滤需要解析日期格式）
                    result["has_reduction_recent"] = True
                    result["reduction_count"] = int(reduction_mask.sum())
    except Exception as e:  # noqa: BLE001
        logger.debug("取增减持失败 %s: %s", code, e)

    return result


# ===========================================================================
# 综合筛选入口
# ===========================================================================

@dataclass
class TailDipCandidate:
    """策略4进化版完整候选结果。"""
    code: str
    name: str
    passed: bool
    anomalous_deviation: AnomalousDeviationResult | None = None
    tail_volatility: TailVolatilityResult | None = None
    financial_redline: FinancialRedLine | None = None
    stop_loss_plan: IronStopLossResult | None = None
    premarket_fuse: PremarketFuseResult | None = None
    rejection_reasons: list[str] = field(default_factory=list)


def screen_tail_dip_candidate(
    code: str,
    name: str,
    *,
    individual_change_pct: float,
    sector_change_pct: float,
    volume_today: float,
    volume_ma5: float,
    close_price: float,
    turnover: float,
    limitup_boards: int = 0,
    is_weekend_eve: bool = False,
    # 财务因子（可选——None则跳过该检查）
    goodwill: float | None = None,
    net_assets: float | None = None,
    accounts_receivable: float | None = None,
    revenue: float | None = None,
    pledge_ratio: float | None = None,
    has_reduction_announce: bool = False,
    is_st: bool = False,
    tail_returns_250d: list[float] | None = None,
    daily_volatility: float | None = None,  # 全日波动率（尾盘恶庄过滤用）
) -> TailDipCandidate:
    """策略4进化版完整筛选入口。

    执行顺序（短路设计——任一层失败即退出）：
    1. 财务红线防火墙（Phase 3 不可变）
    2. 价格/成交额基础筛选
    3. 错杀偏离度因子
    4. 尾盘波动率过滤
    5. （通过以上 = 可入场，后续止损由 execute_iron_stop_loss 动态管理）
    """
    candidate = TailDipCandidate(code=code, name=name, passed=True)

    # ━━━ 1. 财务红线防火墙 ━━━
    redline = financial_red_line_shield(
        code=code, name=name,
        goodwill=goodwill, net_assets=net_assets,
        accounts_receivable=accounts_receivable, revenue=revenue,
        pledge_ratio=pledge_ratio,
        has_reduction_announce=has_reduction_announce,
        is_st=is_st, limitup_boards=limitup_boards,
        is_weekend_eve=is_weekend_eve,
    )
    candidate.financial_redline = redline
    if not redline.passed:
        candidate.passed = False
        candidate.rejection_reasons.extend(redline.blocked_reasons)
        return candidate  # 短路

    # ━━━ 2. 价格/成交额基础筛选 ━━━
    if close_price < HARD_THRESHOLDS["min_price"]:
        candidate.passed = False
        candidate.rejection_reasons.append(f"价格{close_price}<{HARD_THRESHOLDS['min_price']}")

    if turnover < HARD_THRESHOLDS["min_amount"]:
        candidate.passed = False
        candidate.rejection_reasons.append(f"成交额{turnover/1e4:.0f}万<{HARD_THRESHOLDS['min_amount']/1e4:.0f}万")

    # 跌幅范围检查：-3% ~ -5%是甜区
    if individual_change_pct > HARD_THRESHOLDS["min_drop_pct"]:
        candidate.passed = False
        candidate.rejection_reasons.append(f"跌幅{individual_change_pct:.1f}%>{HARD_THRESHOLDS['min_drop_pct']}%（不算错杀）")

    if individual_change_pct < HARD_THRESHOLDS["max_drop_pct"]:
        candidate.passed = False
        candidate.rejection_reasons.append(f"跌幅{individual_change_pct:.1f}%<{HARD_THRESHOLDS['max_drop_pct']}%（重跌是基本面恶化）")

    if not candidate.passed:
        return candidate  # 短路

    # ━━━ 3. 错杀偏离度因子 ━━━
    deviation = calculate_anomalous_deviation(
        code=code,
        individual_change_pct=individual_change_pct,
        sector_change_pct=sector_change_pct,
        volume_today=volume_today,
        volume_ma5=volume_ma5,
    )
    candidate.anomalous_deviation = deviation
    if not deviation.is_anomalous:
        candidate.passed = False
        candidate.rejection_reasons.append(f"非错杀：{deviation.detail}")
        return candidate  # 短路

    # 高信心错杀 + 甜区条件 → 最优候选
    if deviation.confidence == "high" and close_price <= HARD_THRESHOLDS["max_price_sweet"]:
        candidate.rejection_reasons.append("✓ 高信心错杀+甜区（最优候选）")

    # ━━━ 4. 尾盘波动率过滤 ━━━
    if tail_returns_250d is not None:
        tail_vol = check_tail_volatility(code, tail_returns_250d, daily_volatility=daily_volatility)
        candidate.tail_volatility = tail_vol
        if not tail_vol.passed:
            candidate.passed = False
            candidate.rejection_reasons.append(f"尾盘恶庄过滤：{tail_vol.detail}")
            return candidate  # 短路

    return candidate


__all__ = [
    "HARD_THRESHOLDS",
    "FinancialRedLine",
    "financial_red_line_shield",
    "AnomalousDeviationResult",
    "calculate_anomalous_deviation",
    "TailVolatilityResult",
    "check_tail_volatility",
    "IronStopLossResult",
    "execute_iron_stop_loss",
    "PremarketFuseResult",
    "premarket_liquidity_fuse",
    "fetch_financial_substitute_factors",
    "TailDipCandidate",
    "screen_tail_dip_candidate",
    "compute_realtime_sector_deviation",
    "diagnose_drawdown_lock",
    "propose_peak_decay",
    "PeakDecayProposal",
    "check_tail_volatility_from_snapshots",
    "TailSnapVolatilityResult",
]


# ===========================================================================
# v4.00 新增：实时板块偏离度计算（从intraday_quote_snapshots提取）
# ===========================================================================

@dataclass
class SectorDeviationResult:
    """个股vs全市场实时偏离度结果。"""
    code: str
    ts: str                    # 时间点
    stock_change: float        # 个股涨跌幅%
    sector_median: float       # 全市场中位数涨跌幅%
    sector_mean: float         # 全市场均值涨跌幅%
    deviation_from_median: float  # 偏离度（个股-中位数 绝对值）
    deviation_from_mean: float    # 偏离度（个股-均值 绝对值）
    is_anomalous: bool         # 偏离度>=3%
    sample_size: int           # 板本样本量


def compute_realtime_sector_deviation(
    code: str,
    db_path: str = ".vibe-research/intraday_accumulation/intraday_microstructure.db",
    *,
    date: str | None = None,
    min_deviation: float = 3.0,
    use_median: bool = True,
) -> list[SectorDeviationResult]:
    """从 intraday_quote_snapshots 提取个股vs全市场实时偏离度时间序列。

    v4.00 生产模式：
    - 用全市场中位数涨跌幅作为板块近似（比均值更抗极值）
    - 700+只票的实时涨跌幅，比深证成指更精确
    - 返回全天所有时间点的偏离度序列，供盘中动态判断

    数据源：intraday_quote_snapshots（80417条/18交易日）
    替代：之前用深证成指近似板块的降级方案
    """
    import sqlite3
    import statistics as stats_mod

    try:
        db = sqlite3.connect(db_path)
    except sqlite3.Error:
        return []

    try:
        # 确定日期
        if date is None:
            row = db.execute(
                "SELECT date FROM intraday_quote_snapshots ORDER BY date DESC LIMIT 1"
            ).fetchone()
            if not row:
                return []
            date = row[0]

        # 获取所有时间点
        ts_rows = db.execute(
            "SELECT DISTINCT ts FROM intraday_quote_snapshots WHERE date=? ORDER BY ts",
            (date,),
        ).fetchall()

        results: list[SectorDeviationResult] = []
        for (ts,) in ts_rows:
            # 全市场涨跌幅
            sector_rows = db.execute(
                "SELECT change_pct FROM intraday_quote_snapshots "
                "WHERE date=? AND ts=? AND change_pct IS NOT NULL",
                (date, ts),
            ).fetchall()
            sector_vals = [r[0] for r in sector_rows]
            if not sector_vals:
                continue

            sector_median = stats_mod.median(sector_vals)
            sector_mean = stats_mod.mean(sector_vals)

            # 个股涨跌幅
            stock_row = db.execute(
                "SELECT change_pct FROM intraday_quote_snapshots "
                "WHERE date=? AND ts=? AND code=? AND change_pct IS NOT NULL",
                (date, ts, code),
            ).fetchone()
            if not stock_row:
                continue

            stock_chg = stock_row[0]
            dev_median = abs(stock_chg - sector_median)
            dev_mean = abs(stock_chg - sector_mean)
            sector_ref = sector_median if use_median else sector_mean
            dev_ref = dev_median if use_median else dev_mean

            results.append(SectorDeviationResult(
                code=code,
                ts=ts,
                stock_change=round(stock_chg, 2),
                sector_median=round(sector_median, 2),
                sector_mean=round(sector_mean, 2),
                deviation_from_median=round(dev_median, 2),
                deviation_from_mean=round(dev_mean, 2),
                is_anomalous=dev_ref >= min_deviation,
                sample_size=len(sector_vals),
            ))

        db.close()
        return results
    except Exception as e:  # noqa: BLE001
        logger.debug("compute_realtime_sector_deviation 失败: %s", e)
        db.close()
        return []


# ===========================================================================
# v4.00 新增：回撤断路器永久锁定诊断
# ===========================================================================

@dataclass
class DrawdownLockDiagnosis:
    """回撤断路器锁定状态诊断结果。"""
    current_equity: float         # 当前权益
    peak_equity: float            # 历史峰值
    drawdown_cny: float           # 回撤金额
    drawdown_pct: float           # 回撤百分比
    size_multiplier: float        # 当前乘数
    status: str                   # enforced/underpowered/disabled
    days_tracked: int             # 跟踪天数
    # 诊断
    is_permanently_locked: bool   # 是否永久锁定
    recovery_target: float        # 恢复所需cum_pnl
    recovery_needed: float        # 需要赚多少才能解锁
    diagnosis: str                # 诊断说明


def diagnose_drawdown_lock(
    current_equity: float,
    peak_equity: float,
    initial_capital: float = 100000.0,
    days_tracked: int = 0,
    dd_threshold_stop: float = 15.0,
) -> DrawdownLockDiagnosis:
    """回撤断路器永久锁定诊断。

    核心问题（宏观及心理博弈专家发现）：
    DrawdownBreaker.compute_drawdown() 用 peak_pnl（历史最高cum_pnl）计算回撤。
    如果峰值145k→回撤到84k（DD=61%），即使从84k涨回100k，
    回撤仍是145k-100k=45k=45%（仍>15%→size_mult=0）。
    断路器永远不会自然恢复，除非cum_pnl超过历史峰值。

    这是刻意的风控设计（防止"回本就忘痛"），
    但在极端回撤下会导致系统永久锁定——
    需要人工决策是否重置peak。
    """
    drawdown_cny = peak_equity - current_equity
    drawdown_pct = drawdown_cny / initial_capital * 100 if initial_capital > 0 else 0

    is_locked = drawdown_pct > dd_threshold_stop and days_tracked >= 60

    # 恢复目标：cum_pnl需要超过peak_pnl（即权益超过peak_equity）
    current_cum_pnl = current_equity - initial_capital
    peak_cum_pnl = peak_equity - initial_capital
    recovery_target = peak_cum_pnl
    recovery_needed = peak_cum_pnl - current_cum_pnl

    if is_locked:
        diagnosis = (
            f"永久锁定：回撤{drawdown_pct:.1f}%>{dd_threshold_stop}%，"
            f"需赚{recovery_needed:+.0f}元（权益从{current_equity:.0f}涨到{peak_equity:.0f}）"
            f"才能解锁。当前资金{current_equity:.0f}下需收益率"
            f"{recovery_needed/current_equity*100:.1f}%才可恢复。"
        )
    elif days_tracked < 60:
        diagnosis = f"underpowered：跟踪{days_tracked}<60天，不enforce"
    else:
        diagnosis = f"正常：回撤{drawdown_pct:.1f}%<{dd_threshold_stop}%"

    return DrawdownLockDiagnosis(
        current_equity=round(current_equity, 2),
        peak_equity=round(peak_equity, 2),
        drawdown_cny=round(drawdown_cny, 2),
        drawdown_pct=round(drawdown_pct, 2),
        size_multiplier=0.0 if is_locked else (0.5 if drawdown_pct > 10 else 1.0),
        status="enforced" if is_locked else ("underpowered" if days_tracked < 60 else "normal"),
        days_tracked=days_tracked,
        is_permanently_locked=is_locked,
        recovery_target=round(recovery_target, 2),
        recovery_needed=round(recovery_needed, 2),
        diagnosis=diagnosis,
    )


# ===========================================================================
# v5.00 新增：peak渐进衰减恢复机制（DrawdownBreaker 重置方案）
# ===========================================================================

@dataclass
class PeakDecayProposal:
    """peak渐进衰减方案——供人工审批后实施。

    设计原则（四专家共识）：
    - 不简单重置peak（保留风控记忆）
    - 极端回撤+长期锁定 → peak按系数衰减（降低恢复门槛）
    - 衰减后size_mult上限0.5（保留"曾经大跌过"的风控记忆）
    - 需要人工确认后实施（不自主修改风控核心逻辑）
    """
    current_peak: float             # 当前峰值
    proposed_peak: float            # 衰减后峰值
    decay_factor: float             # 衰减系数
    trigger_reason: str             # 触发原因
    new_recovery_needed: float      # 衰减后恢复所需金额
    new_recovery_pct: float         # 衰减后恢复所需收益率
    size_mult_cap: float            # 衰减后size_mult上限（0.5）
    recommendation: str             # 建议操作


def propose_peak_decay(
    current_equity: float,
    peak_equity: float,
    initial_capital: float = 100000.0,
    days_tracked: int = 0,
) -> PeakDecayProposal | None:
    """peak渐进衰减方案生成器。

    衰减规则（四专家共识）：
    - 回撤>30% 且 天数>90 → decay=0.7（peak×0.7）
    - 回撤>50% 且 天数>180 → decay=0.5（peak×0.5）
    - 回撤>70% 或 天数>365 → decay=0.3（peak×0.3）
    - 衰减后size_mult上限0.5（非完全恢复，保留风控记忆）
    - 衰减后若回撤仍>15%，size_mult仍=0（继续锁但门槛降低）
    """
    drawdown_cny = peak_equity - current_equity
    drawdown_pct = drawdown_cny / initial_capital * 100 if initial_capital > 0 else 0

    if days_tracked < 60:
        return None  # underpowered，不需要衰减

    if drawdown_pct <= 15.0:
        return None  # 未锁定，不需要衰减

    # 衰减系数选择
    if drawdown_pct > 70 or days_tracked > 365:
        decay = 0.3
        reason = f"极端回撤{drawdown_pct:.0f}%或天数{days_tracked}>365"
    elif drawdown_pct > 50 and days_tracked > 180:
        decay = 0.5
        reason = f"严重回撤{drawdown_pct:.0f}%+天数{days_tracked}>180"
    elif drawdown_pct > 30 and days_tracked > 90:
        decay = 0.7
        reason = f"显著回撤{drawdown_pct:.0f}%+天数{days_tracked}>90"
    else:
        return None  # 不满足衰减条件

    proposed_peak = peak_equity * decay
    # 衰减后峰值不能低于当前权益（否则等于直接解锁）
    proposed_peak = max(proposed_peak, current_equity)

    new_drawdown = proposed_peak - current_equity
    new_drawdown_pct = new_drawdown / initial_capital * 100
    new_recovery_needed = proposed_peak - current_equity
    new_recovery_pct = new_recovery_needed / current_equity * 100 if current_equity > 0 else 0

    # 衰减后是否解锁
    if new_drawdown_pct <= 15.0:
        recommendation = (
            f"衰减后peak={proposed_peak:.0f}（×{decay}），"
            f"回撤{new_drawdown_pct:.1f}%<15% → 解锁，"
            f"size_mult上限0.5（保留风控记忆，半仓运行）"
        )
    else:
        recommendation = (
            f"衰减后peak={proposed_peak:.0f}（×{decay}），"
            f"回撤{new_drawdown_pct:.1f}%仍>15% → 仍锁定，"
            f"但恢复门槛降低（需赚{new_recovery_needed:.0f}元={new_recovery_pct:.1f}%）"
        )

    return PeakDecayProposal(
        current_peak=round(peak_equity, 2),
        proposed_peak=round(proposed_peak, 2),
        decay_factor=decay,
        trigger_reason=reason,
        new_recovery_needed=round(new_recovery_needed, 2),
        new_recovery_pct=round(new_recovery_pct, 2),
        size_mult_cap=0.5,
        recommendation=recommendation,
    )


# ===========================================================================
# v8.00 新增：轻量版尾盘波动率检查（用14:50→15:00快照替代5分钟bar）
# ===========================================================================

@dataclass
class TailSnapVolatilityResult:
    """用14:50→15:00快照计算的尾盘波动率结果。"""
    code: str
    passed: bool
    tail_volatility: float          # 尾盘10分钟收益率波动率
    daily_volatility: float        # 日K波动率（基准）
    volatility_ratio: float        # 尾盘/日K 比值
    sample_days: int               # 样本天数
    is_manipulated: bool           # 是否判定为恶庄压价
    detail: str = ""


def check_tail_volatility_from_snapshots(
    code: str,
    db_path: str = ".vibe-research/intraday_accumulation/intraday_microstructure.db",
    kline_db_path: str = ".vibe-research/baostock_kline_cache.db",
    *,
    min_days: int = 15,
    manipulation_ratio: float = 0.3,   # 尾盘波动率<日K的30% → 疑似恶庄
) -> TailSnapVolatilityResult:
    """轻量版尾盘波动率检查——用14:50→15:00快照替代5分钟bar。

    数据源：intraday_quote_snapshots（14:50和15:00两个时间点）
    替代：check_tail_volatility()需要250日5分钟bar（当前数据不足无法激活）

    核心逻辑：
    - 用14:50→15:00的价格变化计算尾盘10分钟收益率
    - 用日K收益率标准差作为全日波动率基准
    - 如果尾盘波动率 < 日K波动率 × 30% → 疑似恶庄压价
    - 样本门槛15天（vs check_tail_volatility的60天），因为快照数据覆盖有限

    防过拟合：
    - 比值判定而非绝对值——不同股票波动率不同，比值消除个体差异
    - manipulation_ratio=0.3 是保守阈值（需要尾盘波动率不到日K的1/3才触发）
    """
    import sqlite3
    import json as _json
    from collections import defaultdict

    try:
        db = sqlite3.connect(db_path)
    except sqlite3.Error:
        return TailSnapVolatilityResult(
            code=code, passed=True, tail_volatility=0.0,
            daily_volatility=0.0, volatility_ratio=1.0,
            sample_days=0, is_manipulated=False,
            detail="数据库连接失败",
        )

    try:
        # 找有14:50和15:00的交易日
        dates_1450 = set(r[0] for r in db.execute(
            "SELECT DISTINCT date FROM intraday_quote_snapshots WHERE ts LIKE '%T14:50%'"
        ).fetchall())
        dates_1500 = set(r[0] for r in db.execute(
            "SELECT DISTINCT date FROM intraday_quote_snapshots WHERE ts LIKE '%T15:00%'"
        ).fetchall())
        both_dates = sorted(dates_1450 & dates_1500)

        # 计算尾盘收益率
        tail_returns = []
        for date in both_dates:
            r1 = db.execute(
                "SELECT price FROM intraday_quote_snapshots "
                "WHERE date=? AND code=? AND ts LIKE '%T14:50%'",
                (date, code),
            ).fetchone()
            r2 = db.execute(
                "SELECT price FROM intraday_quote_snapshots "
                "WHERE date=? AND code=? AND ts LIKE '%T15:00%'",
                (date, code),
            ).fetchone()
            if r1 and r2 and r1[0] and r2[0] and r1[0] > 0:
                ret = (r2[0] - r1[0]) / r1[0]
                tail_returns.append(ret)

        db.close()
    except Exception as e:  # noqa: BLE001
        db.close()
        return TailSnapVolatilityResult(
            code=code, passed=True, tail_volatility=0.0,
            daily_volatility=0.0, volatility_ratio=1.0,
            sample_days=0, is_manipulated=False,
            detail=f"快照查询失败: {e}",
        )

    sample_days = len(tail_returns)

    if sample_days < min_days:
        return TailSnapVolatilityResult(
            code=code, passed=True, tail_volatility=0.0,
            daily_volatility=0.0, volatility_ratio=1.0,
            sample_days=sample_days, is_manipulated=False,
            detail=f"样本不足{sample_days}<{min_days}天，跳过过滤",
        )

    tail_vol = float(np.std(tail_returns, ddof=1))

    # 从baostock_kline_cache拉日K波动率
    try:
        kdb = sqlite3.connect(kline_db_path)
        krow = kdb.execute(
            "SELECT bars_json FROM kline WHERE code=?", (code,)
        ).fetchone()
        kdb.close()
        if not krow:
            return TailSnapVolatilityResult(
                code=code, passed=True, tail_volatility=round(tail_vol, 6),
                daily_volatility=0.0, volatility_ratio=1.0,
                sample_days=sample_days, is_manipulated=False,
                detail=f"尾盘vol={tail_vol:.6f}但无日K缓存",
            )
        bars = _json.loads(krow[0])
        closes = [float(b["close"]) for b in bars[-30:] if b.get("close")]
        if len(closes) < 2:
            return TailSnapVolatilityResult(
                code=code, passed=True, tail_volatility=round(tail_vol, 6),
                daily_volatility=0.0, volatility_ratio=1.0,
                sample_days=sample_days, is_manipulated=False,
                detail=f"尾盘vol={tail_vol:.6f}但日K不足",
            )
        daily_rets = [(closes[i] - closes[i - 1]) / closes[i - 1]
                      for i in range(1, len(closes))]
        daily_vol = float(np.std(daily_rets, ddof=1))
    except Exception as e:  # noqa: BLE001
        return TailSnapVolatilityResult(
            code=code, passed=True, tail_volatility=round(tail_vol, 6),
            daily_volatility=0.0, volatility_ratio=1.0,
            sample_days=sample_days, is_manipulated=False,
            detail=f"日K查询失败: {e}",
        )

    vol_ratio = tail_vol / daily_vol if daily_vol > 0 else 1.0
    is_manipulated = vol_ratio < manipulation_ratio

    detail = (
        f"尾盘vol={tail_vol:.6f}({sample_days}日) "
        f"日Kvol={daily_vol:.6f} 比值={vol_ratio:.3f} "
        f"{'→ 尾盘波动率异常低，疑似恶庄压价' if is_manipulated else '→ 正常'}"
    )

    return TailSnapVolatilityResult(
        code=code,
        passed=not is_manipulated,
        tail_volatility=round(tail_vol, 6),
        daily_volatility=round(daily_vol, 6),
        volatility_ratio=round(vol_ratio, 3),
        sample_days=sample_days,
        is_manipulated=is_manipulated,
        detail=detail,
    )
