# -*- coding: utf-8 -*-
"""一日风险模型 —— 个股单日风险量化（客观数据，非行动建议）。"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel

import astock


class OneDayRisk(BaseModel):
    """个股单日风险（客观数据，非行动建议）。"""

    code: str
    date: str
    # 动态评分（实时更新）
    risk_score: float = 50.0              # 风险评分 (0-100)，随资金流动态变化
    risk_level: str = "MEDIUM"            # HIGH/MEDIUM/LOW，基于risk_score动态判定
    score_components: dict = {}           # 各维度得分明细（用于解释）
    # 资金流维度（动态）
    capital_flow_signal: float = 0.0      # 资金流信号 (-1 到 +1)，实时更新
    capital_flow_trend: str = ""          # 流入/流出/震荡，基于时序判断
    big_fund_detected: bool = False       # 是否检测到大基金
    big_fund_type: str = ""               # 大基金类型 (游资/机构/北向)
    fund_flow_history: list[dict] = []    # 近5日资金流历史（用于趋势判断）
    # 龙虎榜维度（半动态）
    dragon_tiger_risk: float = 0.0        # 龙虎榜风险评分（T+1更新）
    one_day_seats: list[str] = []         # 一日游特征席位
    multi_seat_signal: bool = False       # 多席位同时出现信号
    seat_confidence: float = 0.0          # 席位识别置信度
    # 综合判断
    recommendation: str = ""              # 建议 (关注风险/谨慎参与/可正常参与)
    factors: list[str] = []               # 风险因素列表
    last_updated: str = ""                # 最后更新时间（用于前端展示时效性）
    # 动态阈值
    dynamic_thresholds: dict = {}         # 基于市场环境的动态阈值
    # 原有字段（保留兼容）
    risk_factors: list[str] = []
    max_drawdown: float = 0.0
    volatility: float = 0.0
    liquidity_risk: float = 0.0
    concentration_risk: float = 0.0


from config import default_config


# ===========================================================================
# 动态阈值配置（基于 STI 阶段）
# ===========================================================================

_DYNAMIC_THRESHOLDS = default_config.RISK_DYNAMIC_THRESHOLDS


def get_dynamic_thresholds(sti_phase: str | None = None) -> dict:
    """获取基于 STI 阶段的动态阈值。"""
    if sti_phase and sti_phase in _DYNAMIC_THRESHOLDS:
        return _DYNAMIC_THRESHOLDS[sti_phase]
    return _DYNAMIC_THRESHOLDS["DIVERGENCE"]  # 默认分歧期


# ===========================================================================
# 资金流趋势判断
# ===========================================================================

def calculate_capital_flow_trend(fund_flow_history: list[dict]) -> str:
    """根据近5日资金流历史判断趋势。"""
    if not fund_flow_history or len(fund_flow_history) < 2:
        return "震荡"

    signals = []
    for entry in fund_flow_history[-5:]:
        signal = entry.get("capital_flow_signal", 0)
        if isinstance(signal, (int, float)):
            signals.append(float(signal))

    if len(signals) < 2:
        return "震荡"

    # 简单趋势判断：最近3日信号均值 vs 前2日信号均值
    recent = sum(signals[-3:]) / len(signals[-3:])
    previous = sum(signals[:2]) / len(signals[:2])

    if recent > previous + 0.1:
        return "流入"
    if recent < previous - 0.1:
        return "流出"
    return "震荡"


# ===========================================================================
# 动态风险评分更新
# ===========================================================================

async def calculate_base_risk(code: str) -> float:
    """计算个股基础风险评分（静态部分）。"""
    try:
        import limitup_screener as ls
        result = await ls.get_screener_result()
        for g in result.gene_scores:
            if g.code == code:
                # 基于基因得分反推风险：得分越高，风险越低
                base_score = max(0.0, 100.0 - g.total_score)
                return round(base_score, 2)
    except Exception:
        pass
    return 50.0


def calculate_flow_adjustment(capital_flow: dict) -> float:
    """根据资金流数据计算风险调整值。"""
    signal = capital_flow.get("capital_flow_signal", 0)
    if not isinstance(signal, (int, float)):
        return 0.0

    # 资金流信号 (-1 到 +1)，负值表示流出，增加风险
    adjustment = -signal * 20.0
    return round(adjustment, 2)


async def get_current_sti_phase() -> str | None:
    """获取当前 STI 阶段（用于动态阈值）。"""
    try:
        import limitup_sti as ls_sti
        engine = ls_sti.get_sti_engine()
        db = engine._get_db()
        row = db.execute(
            "SELECT phase FROM sti_timeline WHERE phase IS NOT NULL ORDER BY date DESC LIMIT 1"
        ).fetchone()
        if row:
            return row["phase"]
    except Exception:
        pass
    return None


async def update_one_day_risk_realtime(code: str) -> OneDayRisk:
    """实时更新一日游风险评分（V2.0.2 动态化）。"""
    # 1. 获取基础风险评分
    base_score = await calculate_base_risk(code)

    # 2. 获取最新资金流数据（模拟：实际应接入实时资金流接口）
    capital_flow = _get_realtime_capital_flow(code)
    flow_adjustment = calculate_flow_adjustment(capital_flow)
    dynamic_score = base_score + flow_adjustment
    dynamic_score = max(0.0, min(100.0, dynamic_score))

    # 3. 动态阈值调整（基于 STI 阶段）
    sti_phase = await get_current_sti_phase()
    thresholds = get_dynamic_thresholds(sti_phase)

    # 4. 判定风险等级
    if dynamic_score >= thresholds["high"]:
        risk_level = "HIGH"
    elif dynamic_score >= thresholds["medium"]:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    # 5. 资金流趋势判断
    fund_flow_history = capital_flow.get("fund_flow_history", [])
    capital_flow_trend = calculate_capital_flow_trend(fund_flow_history)

    # 6. 龙虎榜风险评分（T+1 更新）
    dragon_tiger_risk = await _get_dragon_tiger_risk(code)

    # 7. 席位信息（一日游特征席位 + 多席位信号）
    seat_info = await _get_seat_info(code)
    one_day_seats = seat_info.get("one_day_seats", [])
    multi_seat_signal = seat_info.get("multi_seat_signal", False)
    seat_confidence = seat_info.get("seat_confidence", 0.0)

    # 8. 波动率与回撤（基于近期行情）
    volatility = await _calculate_volatility(code)
    max_drawdown = await _calculate_max_drawdown(code)
    liquidity_risk = await _calculate_liquidity_risk(code)
    concentration_risk = await _calculate_concentration_risk(code)

    # 9. 综合风险因素与建议
    factors, recommendation = _build_risk_factors(
        dynamic_score=dynamic_score,
        risk_level=risk_level,
        dragon_tiger_risk=dragon_tiger_risk,
        volatility=volatility,
        max_drawdown=max_drawdown,
        liquidity_risk=liquidity_risk,
        concentration_risk=concentration_risk,
        capital_flow_trend=capital_flow_trend,
        multi_seat_signal=multi_seat_signal,
    )

    # 10. 构建动态风险对象
    return OneDayRisk(
        code=code,
        date=datetime.now().strftime("%Y-%m-%d"),
        risk_score=round(dynamic_score, 2),
        risk_level=risk_level,
        score_components={
            "base_score": base_score,
            "flow_adjustment": flow_adjustment,
            "final_score": round(dynamic_score, 2),
        },
        capital_flow_signal=capital_flow.get("capital_flow_signal", 0.0),
        capital_flow_trend=capital_flow_trend,
        big_fund_detected=capital_flow.get("big_fund_detected", False),
        big_fund_type=capital_flow.get("big_fund_type", ""),
        fund_flow_history=fund_flow_history,
        dragon_tiger_risk=dragon_tiger_risk,
        one_day_seats=one_day_seats,
        multi_seat_signal=multi_seat_signal,
        seat_confidence=seat_confidence,
        recommendation=recommendation,
        factors=factors,
        last_updated=datetime.now().isoformat(),
        dynamic_thresholds=thresholds,
        risk_factors=factors,
        max_drawdown=max_drawdown,
        volatility=volatility,
        liquidity_risk=liquidity_risk,
        concentration_risk=concentration_risk,
    )


# ===========================================================================
# 龙虎榜与席位风险计算
# ===========================================================================

async def _get_dragon_tiger_risk(code: str) -> float:
    """计算龙虎榜风险评分（0-100，越高风险越大）。"""
    try:
        import astock
        from fallback import get_with_fallback
        cache_key = f"dragon_tiger:{code}"
        dt = get_with_fallback(
            cache_key,
            lambda: astock.dragon_tiger_board(code, look_back=30),
            ttl=600,  # 10 分钟缓存
            fallback_value={"records": []},
        )
        records = dt.get("records", [])
        if not records:
            return 0.0

        # 基于近期上榜频率和净买入额波动计算风险
        recent_days = len(records)
        net_amounts = [r.get("net_buy", 0) for r in records[:5]]
        avg_net = sum(net_amounts) / len(net_amounts) if net_amounts else 0

        # 上榜频率风险（5次以上加分）
        frequency_risk = min(recent_days * 5, 30)

        # 净买入波动风险
        if len(net_amounts) >= 2:
            variance = sum((x - avg_net) ** 2 for x in net_amounts) / len(net_amounts)
            volatility_risk = min(variance / 1000, 30)  # 归一化
        else:
            volatility_risk = 0

        return round(frequency_risk + volatility_risk, 2)
    except Exception:
        return 0.0


async def _get_seat_info(code: str) -> dict:
    """获取席位信息（一日游特征席位 + 多席位信号）。"""
    try:
        import seat_engine as se
        from fallback import get_with_fallback
        cache_key = f"seat_info:{code}"
        signal = get_with_fallback(
            cache_key,
            lambda: se.get_engine().compute_consensus_signal(
                datetime.now(se.BEIJING_TZ).strftime("%Y-%m-%d"),
                code,
            ),
            ttl=600,  # 10 分钟缓存
            fallback_value=None,
        )
        if not signal:
            return {
                "one_day_seats": [],
                "multi_seat_signal": False,
                "seat_confidence": 0.0,
            }

        details = signal.get("details", {})
        buy_seats = details.get("buy_seats", [])
        sell_seats = details.get("sell_seats", [])

        # 一日游特征席位：当日买入且近期未持续出现的席位
        one_day_seats = []
        for seat in buy_seats:
            name = seat.get("name", "")
            if name and seat.get("net", 0) > 0:
                one_day_seats.append(name)

        # 多席位信号：买入侧出现 2+ 种不同类型的资金
        buy_types = {s.get("seat_type") for s in buy_seats if s.get("seat_type")}
        multi_seat_signal = len({t for t in buy_types if t != "未知席位"}) >= 2

        # 席位置信度：基于机构占比和净买入额
        total_buy = details.get("total_buy_amount", 0)
        inst_buy = details.get("institution_buy_amt", 0)
        if total_buy > 0:
            confidence = min(inst_buy / total_buy, 1.0) * 100
        else:
            confidence = 0.0

        return {
            "one_day_seats": one_day_seats[:5],  # 最多5个
            "multi_seat_signal": multi_seat_signal,
            "seat_confidence": round(confidence, 2),
        }
    except Exception:
        return {
            "one_day_seats": [],
            "multi_seat_signal": False,
            "seat_confidence": 0.0,
        }


# ===========================================================================
# 波动率、回撤与风险指标计算
# ===========================================================================

async def _calculate_volatility(code: str, window: int = 20) -> float:
    """计算近 window 日收益率标准差（波动率）。"""
    try:
        import astock
        kline = astock.get_kline(code, days=window + 10)
        closes = [k["close"] for k in kline[-window:]]
        if len(closes) < 2:
            return 0.0
        returns = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
        ]
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        return round(variance ** 0.5 * 100, 2)  # 百分比
    except Exception:
        return 0.0


async def _calculate_max_drawdown(code: str, window: int = 60) -> float:
    """计算近 window 日最大回撤（百分比）。"""
    try:
        import astock
        kline = astock.get_kline(code, days=window + 10)
        closes = [k["close"] for k in kline[-window:]]
        if len(closes) < 2:
            return 0.0
        peak = closes[0]
        max_dd = 0.0
        for c in closes[1:]:
            if c > peak:
                peak = c
            dd = (peak - c) / peak
            if dd > max_dd:
                max_dd = dd
        return round(max_dd * 100, 2)
    except Exception:
        return 0.0


async def _calculate_liquidity_risk(code: str) -> float:
    """计算流动性风险（基于近20日平均成交额，越低风险越高）。"""
    try:
        import astock
        kline = astock.get_kline(code, days=20)
        amounts = [k.get("amount", 0) for k in kline]
        if not amounts:
            return 0.0
        avg_amount = sum(amounts) / len(amounts)
        # 成交额低于 5000 万视为高流动性风险
        if avg_amount < 50000000:
            return round(100 - avg_amount / 50000000 * 100, 2)
        return 0.0
    except Exception:
        return 0.0


async def _calculate_concentration_risk(code: str) -> float:
    """计算集中度风险（基于龙虎榜席位集中度）。"""
    try:
        import astock
        dt = astock.dragon_tiger_board(code, look_back=10)
        records = dt.get("records", [])
        if not records:
            return 0.0

        # 计算最近一次上榜的席位集中度（CR5）
        latest = records[0]
        net_buys = [r.get("net_buy", 0) for r in records[:5]]
        total = sum(net_buys)
        if total <= 0:
            return 0.0

        # 计算前5席位的集中度
        top5 = sum(sorted(net_buys, reverse=True)[:5])
        concentration = top5 / total if total > 0 else 0
        return round(concentration * 100, 2)
    except Exception:
        return 0.0


# ===========================================================================
# 风险因素与建议生成
# ===========================================================================

def _build_risk_factors(
    dynamic_score: float,
    risk_level: str,
    dragon_tiger_risk: float,
    volatility: float,
    max_drawdown: float,
    liquidity_risk: float,
    concentration_risk: float,
    capital_flow_trend: str,
    multi_seat_signal: bool,
) -> tuple[list[str], str]:
    """根据各维度指标生成风险因素列表和建议。"""
    factors: list[str] = []
    if dragon_tiger_risk > 30:
        factors.append(f"龙虎榜风险较高({dragon_tiger_risk})")
    if volatility > 5:
        factors.append(f"波动率偏高({volatility}%)")
    if max_drawdown > 10:
        factors.append(f"近期回撤较大({max_drawdown}%)")
    if liquidity_risk > 0:
        factors.append(f"流动性风险({liquidity_risk})")
    if concentration_risk > 60:
        factors.append(f"席位集中度较高({concentration_risk}%)")
    if capital_flow_trend == "流出":
        factors.append("资金流呈流出趋势")
    if multi_seat_signal:
        factors.append("多席位共识信号")

    if not factors:
        factors.append("当前风险因素较少")

    # 建议生成（教育性，非行动建议）
    if risk_level == "HIGH":
        recommendation = "风险评分较高，建议关注风险控制，谨慎参与"
    elif risk_level == "MEDIUM":
        recommendation = "风险适中，建议结合自身风险承受能力评估"
    else:
        recommendation = "风险相对较低，但仍需关注市场变化"

    return factors, recommendation


# ===========================================================================
# 实时资金流数据获取（接入 a-stock-data 东财资金流）
# ===========================================================================

def _get_realtime_capital_flow(code: str) -> dict:
    """获取实时资金流数据（接入东财 push2his 资金流接口）。

    数据源：astock.stock_fund_flow_120d(code)
    返回近 120 交易日资金流，包含主力/大单/超大单净流入。
    降级：东财故障时返回本地缓存或空数据。
    """
    try:
        from fallback import get_with_fallback
        cache_key = f"capital_flow:{code}"
        history = get_with_fallback(
            cache_key,
            lambda: astock.stock_fund_flow_120d(code),
            ttl=600,  # 10 分钟缓存
            fallback_value=[],
        )
    except Exception:
        history = []

    if not history:
        return {
            "capital_flow_signal": 0.0,
            "big_fund_detected": False,
            "big_fund_type": "",
            "fund_flow_history": [],
        }

    # 取最近一日数据
    latest = history[-1]
    main_net = float(latest.get("main_net", 0) or 0)
    super_net = float(latest.get("super_net", 0) or 0)
    large_net = float(latest.get("large_net", 0) or 0)

    # 计算信号强度：以近 120 日主力净流入绝对值的最大值归一化到 [-1, +1]
    max_abs = max((abs(float(h.get("main_net", 0) or 0)) for h in history), default=1.0)
    if max_abs <= 0:
        max_abs = 1.0
    signal = max(-1.0, min(1.0, main_net / max_abs))

    # 大资金检测：超大单 + 大单合计净流入超过阈值
    big_fund_total = super_net + large_net
    big_fund_detected = big_fund_total > 0 and abs(big_fund_total) >= max_abs * 0.1
    big_fund_type = ""
    if big_fund_detected:
        if super_net > 0 and large_net > 0:
            big_fund_type = "超大单+大单"
        elif super_net > 0:
            big_fund_type = "超大单"
        elif large_net > 0:
            big_fund_type = "大单"

    # 转换为资金流历史格式（供趋势判断使用）
    fund_flow_history = [
        {"capital_flow_signal": max(-1.0, min(1.0, float(h.get("main_net", 0) or 0) / max_abs))}
        for h in history[-5:]
    ]

    return {
        "capital_flow_signal": signal,
        "big_fund_detected": big_fund_detected,
        "big_fund_type": big_fund_type,
        "fund_flow_history": fund_flow_history,
    }
