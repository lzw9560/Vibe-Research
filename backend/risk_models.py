# -*- coding: utf-8 -*-
"""一日风险模型 —— 个股单日风险量化（客观数据，非行动建议）。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pydantic import BaseModel

import astock
from data.mappers import dragon_tiger_from_dict, kline_from_mootdx


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
    data_status: str = "ok"               # ok | missing | degraded（数据诚实标记，对齐 sentiment_context:45）
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

async def calculate_base_risk(code: str) -> tuple[float, str]:
    """计算个股基础风险评分（静态部分）。

    返回 (base_score, data_status)：
    - 命中 gene score → (反推风险, 'ok')
    - 未入 screener（合法中性先验）→ (50.0, 'ok')，非故障
    - 取数故障（import/解析异常）→ (50.0, 'missing')，区分故障 vs 合法中性先验

    S111 R7：原 bare except:pass 吞一切无日志。改为 broad catch——任何取数故障
    （含 sqlite3.OperationalError/TypeError/OSError 等 load_gene_scores 的
    conn.execute 可抛的 DB/IO 错）→ 'missing' 并记日志；非异常的未入 screener
    路径已在上面返 'ok'，故障 vs 合法中性先验靠异常路径区分，不靠枚举异常类型。
    """
    try:
        import limitup_screener as ls
        result = await ls.get_screener_result()
        for g in result.gene_scores:
            if g.code == code:
                # 基于基因得分反推风险：得分越高，风险越低
                base_score = max(0.0, 100.0 - g.total_score)
                return round(base_score, 2), "ok"
        # 未入 screener：合法中性先验（非取数故障）
        return 50.0, "ok"
    except Exception as e:
        logging.getLogger("risk_models").warning(
            "calculate_base_risk(%s) 取数失败，降级中性先验 50.0: %s", code, e
        )
        return 50.0, "missing"


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
    base_score, base_status = await calculate_base_risk(code)

    # 2. 获取最新资金流数据（模拟：实际应接入实时资金流接口）
    capital_flow = await asyncio.to_thread(_get_realtime_capital_flow, code)
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
    dragon_tiger_risk, dt_status = await _get_dragon_tiger_risk(code)

    # 7. 席位信息（一日游特征席位 + 多席位信号）
    seat_info = await _get_seat_info(code)
    one_day_seats = seat_info.get("one_day_seats", [])
    multi_seat_signal = seat_info.get("multi_seat_signal", False)
    seat_confidence = seat_info.get("seat_confidence", 0.0)
    seat_status = seat_info.get("data_status", "ok")

    # 8. 波动率与回撤（基于近期行情）
    volatility = await _calculate_volatility(code)
    max_drawdown = await _calculate_max_drawdown(code)
    liquidity_risk = await _calculate_liquidity_risk(code)
    concentration_risk, conc_status = await _calculate_concentration_risk_meta(code)

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

    # 10. 数据诚实性：聚合 data_status（base + 资金流 + risk-trio）；实时资金流非 ok 不戳 now
    cf_status = capital_flow.get("data_status", "ok")
    data_status = _merge_data_status(
        base_status, cf_status, dt_status, seat_status, conc_status
    )
    # last_updated 仍以资金流（实时向量）为准：cf 非 ok 则不戳 now（对齐 S111 R4）；
    # risk-trio 缺失只抬 data_status，不回退 last_updated——risk_score 由 base+cf 决定，
    # trio 缺失只影响 factors/字段值，不影响核心评分时效。
    if cf_status == "ok":
        last_updated = datetime.now().isoformat()
    else:
        # degraded → 用缓存时间；missing → 留空（不伪装刚更新）
        last_updated = capital_flow.get("data_time", "")

    # 11. 构建动态风险对象
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
        last_updated=last_updated,
        data_status=data_status,
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

async def _get_dragon_tiger_risk(code: str) -> tuple[float, str]:
    """计算龙虎榜风险评分（0-100，越高风险越大）。

    返回 (risk_score, data_status)：
    - live 成功、有记录 → (computed, 'ok')
    - fetch 失败/空、命中陈旧缓存 → (0.0, 'degraded')：不基于陈旧算非零风险
    - fetch 失败/空、缓存也空 → (0.0, 'missing')：不伪装"近期未上榜=0风险"
    - 取数/解析异常（mapper/import/infra） → (0.0, 'missing') + logger.warning

    S112 R1：原 bare except: return 0.0 无日志无标记，与"近期未上榜=0风险"同形——
    源断被呈现成 0 风险喂打板（risk_level 可能 HIGH→MEDIUM）。改消费
    get_with_fallback_meta + 返 data_status，对齐 _get_realtime_capital_flow
    (S111 R4) 范式 + :374/:398/:418 warning sibling。
    """
    try:
        from fallback import get_with_fallback_meta
        cache_key = f"dragon_tiger:{code}"
        payload, meta = await asyncio.to_thread(
            get_with_fallback_meta,
            cache_key,
            lambda: astock.dragon_tiger_board(code, look_back=30),
            ttl=600,  # 10 分钟缓存
            fallback_value={"records": []},
        )
        dt = dragon_tiger_from_dict(payload)
    except Exception as e:
        logging.getLogger("risk_models").warning(
            "_get_dragon_tiger_risk(%s) 取数失败，降级 missing: %s", code, e
        )
        return 0.0, "missing"

    # 命中陈旧缓存（源断/限流返空时降级）：不基于陈旧算非零风险，标 degraded（对齐 R4）
    if meta.get("is_stale"):
        return 0.0, "degraded"

    records = dt.records
    if not records:
        # 非陈旧且无记录：fallback_value。S112 over-reporting fix——按 meta.fetch_ok 区分：
        # fetch_ok=True（源正常返空=近期未上龙虎榜）→ ok（合法，非断源）；
        # fetch_ok=False（fetch 抛异常=源断）→ missing。关 R1 silent-zero + 原 crack
        # "源断 vs 未上榜不可区分"诉求（现在可分：ok vs missing）。风险评分仍 0.0。
        return 0.0, "ok" if meta.get("fetch_ok") else "missing"

    # live 成功、有记录 → 正常计算
    # 基于近期上榜频率和净买入额波动计算风险
    recent_days = len(records)
    net_amounts = [r.net_buy or 0 for r in records[:5]]
    avg_net = sum(net_amounts) / len(net_amounts) if net_amounts else 0

    # 上榜频率风险（5次以上加分）
    frequency_risk = min(recent_days * 5, 30)

    # 净买入波动风险
    if len(net_amounts) >= 2:
        variance = sum((x - avg_net) ** 2 for x in net_amounts) / len(net_amounts)
        volatility_risk = min(variance / 1000, 30)  # 归一化
    else:
        volatility_risk = 0

    return round(frequency_risk + volatility_risk, 2), "ok"


async def _get_seat_info(code: str) -> dict:
    """获取席位信息（一日游特征席位 + 多席位信号）。

    返回 dict 含 data_status：
    - live 成功、有 signal → (seats..., 'ok')
    - fetch 失败/空、命中陈旧缓存 → (空..., 'degraded')：不基于陈旧算席位
    - fetch 失败/空、缓存也空 → (空..., 'missing')：不伪装"当日无特征席位"
    - 取数/解析异常 → (空..., 'missing') + logger.warning

    S112 R2：原 fallback=None → 返空 dict 无 data_status，与"当日无特征席位"
    合法结果同形——席位共识信号源断时漏报。改消费 get_with_fallback_meta +
    返 data_status，对齐 R1/R4 范式 + bare except 补 logger（原无日志）。
    """

    def _empty(status: str) -> dict:
        return {
            "one_day_seats": [],
            "multi_seat_signal": False,
            "seat_confidence": 0.0,
            "data_status": status,
        }

    try:
        import seat_engine as se
        from fallback import get_with_fallback_meta
        cache_key = f"seat_info:{code}"
        date_str = datetime.now(se.BEIJING_TZ).strftime("%Y-%m-%d")
        signal, meta = await asyncio.to_thread(
            get_with_fallback_meta,
            cache_key,
            lambda: se.get_engine().compute_consensus_signal(date_str, code),
            ttl=600,  # 10 分钟缓存
            fallback_value=None,
        )
    except Exception as e:
        logging.getLogger("risk_models").warning(
            "_get_seat_info(%s) 取数失败，降级 missing: %s", code, e
        )
        return _empty("missing")

    # 命中陈旧缓存（源断时降级）：不基于陈旧算席位，标 degraded（对齐 R1/R4）
    if meta.get("is_stale"):
        return _empty("degraded")

    if not signal:
        # 非 stale 且 signal 为空：fallback=None。S112 over-reporting fix——按 meta.fetch_ok
        # 区分：fetch_ok=True（源正常返空=当日无特征席位）→ ok（合法）；fetch_ok=False（源断）→ missing。
        # 关 R2 silent-empty + "源断 vs 无特征席位不可区分"诉求。
        return _empty("ok" if meta.get("fetch_ok") else "missing")

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
        "data_status": "ok",
    }


# ===========================================================================
# 波动率、回撤与风险指标计算
# ===========================================================================

async def _calculate_volatility(code: str, window: int = 20) -> float:
    """计算近 window 日收益率标准差（波动率）。"""
    try:
        raw = await asyncio.to_thread(lambda: astock.kline(code, offset=window + 10))
        bars = kline_from_mootdx(code, raw).bars
        closes = [b.close for b in bars[-window:] if b.close is not None]
        if len(closes) < 2:
            return 0.0
        returns = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
        ]
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        return round(variance ** 0.5 * 100, 2)  # 百分比
    except (KeyError, ValueError, TypeError, AttributeError) as e:
        logging.getLogger("risk_models").warning(
            "_calculate_volatility(%s) 取数失败: %s", code, e
        )
        return 0.0


async def _calculate_max_drawdown(code: str, window: int = 60) -> float:
    """计算近 window 日最大回撤（百分比）。"""
    try:
        raw = await asyncio.to_thread(lambda: astock.kline(code, offset=window + 10))
        bars = kline_from_mootdx(code, raw).bars
        closes = [b.close for b in bars[-window:] if b.close is not None]
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
    except (KeyError, ValueError, TypeError, AttributeError) as e:
        logging.getLogger("risk_models").warning(
            "_calculate_max_drawdown(%s) 取数失败: %s", code, e
        )
        return 0.0


async def _calculate_liquidity_risk(code: str) -> float:
    """计算流动性风险（基于近20日平均成交额，越低风险越高）。"""
    try:
        raw = await asyncio.to_thread(lambda: astock.kline(code, offset=20))
        bars = kline_from_mootdx(code, raw).bars
        amounts = [b.turnover or 0 for b in bars]
        if not amounts:
            return 0.0
        avg_amount = sum(amounts) / len(amounts)
        # 成交额低于 5000 万视为高流动性风险
        if avg_amount < 50000000:
            return round(100 - avg_amount / 50000000 * 100, 2)
        return 0.0
    except (KeyError, ValueError, TypeError, AttributeError) as e:
        logging.getLogger("risk_models").warning(
            "_calculate_liquidity_risk(%s) 取数失败: %s", code, e
        )
        return 0.0


async def _calculate_concentration_risk(code: str) -> float:
    """计算集中度风险（基于龙虎榜席位集中度）。

    返 float（向后兼容直调测试 test_s008_t13e_misc）。data_status 由
    _calculate_concentration_risk_meta 返回，update_one_day_risk_realtime 读 _meta。
    """
    score, _status = await _calculate_concentration_risk_meta(code)
    return score


async def _calculate_concentration_risk_meta(code: str) -> tuple[float, str]:
    """集中度风险 + data_status（S112 R3）。

    返回 (concentration, data_status)：
    - live 成功、有记录、total>0 → (computed, 'ok')
    - live 成功、有记录、total<=0 → (0.0, 'ok')（合法无正向净买，非断源）
    - fetch 失败/空、命中陈旧缓存 → (0.0, 'degraded')：不基于陈旧算集中度
    - fetch 失败/空、缓存也空 → (0.0, 'missing')：不伪装"无集中度风险"
    - 取数/解析异常 → (0.0, 'missing') + logger.warning

    原直调 astock.dragon_tiger_board（未走 get_with_fallback 缓存层，更脆，单次断连
    即返空）→ records 空 return 0.0 或 bare except return 0.0，无日志无标记。改套
    get_with_fallback_meta 缓存层（对齐同模块 _get_dragon_tiger_risk）+ 0.0→missing
    + logger，对齐 _get_realtime_capital_flow (S111 R4) 范式 + :374/:398/:418 sibling。
    """
    try:
        from fallback import get_with_fallback_meta
        cache_key = f"concentration_dt:{code}"
        payload, meta = await asyncio.to_thread(
            get_with_fallback_meta,
            cache_key,
            lambda: astock.dragon_tiger_board(code, look_back=10),
            ttl=600,  # 10 分钟缓存
            fallback_value={"records": []},
        )
        dt = dragon_tiger_from_dict(payload)
    except Exception as e:
        logging.getLogger("risk_models").warning(
            "_calculate_concentration_risk(%s) 取数失败，降级 missing: %s", code, e
        )
        return 0.0, "missing"

    # 命中陈旧缓存（源断时降级）：不基于陈旧算集中度，标 degraded（对齐 R1/R4）
    if meta.get("is_stale"):
        return 0.0, "degraded"

    records = dt.records
    if not records:
        # 非陈旧且无记录：fallback_value。S112 over-reporting fix——按 meta.fetch_ok 区分：
        # fetch_ok=True（源正常返空=近期无上榜）→ ok（合法）；fetch_ok=False（源断）→ missing。
        # 关 R3 silent-zero + "源断 vs 无上榜不可区分"诉求。
        return 0.0, "ok" if meta.get("fetch_ok") else "missing"

    # 计算最近一次上榜的席位集中度（CR5）
    net_buys = [r.net_buy or 0 for r in records[:5]]
    total = sum(net_buys)
    if total <= 0:
        # 有记录但无正向净买：合法"无集中度风险"，标 ok（非断源）
        return 0.0, "ok"

    # 计算前5席位的集中度
    top5 = sum(sorted(net_buys, reverse=True)[:5])
    concentration = top5 / total if total > 0 else 0
    return round(concentration * 100, 2), "ok"


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

# 数据诚实性辅助（S111：data_status 聚合 + 空资金流不伪装中性）
_STATUS_SEVERITY = {"ok": 0, "degraded": 1, "missing": 2}


def _merge_data_status(*statuses: str) -> str:
    """取最差 data_status（missing > degraded > ok）。未知值按 ok 处理。"""
    if not statuses:
        return "ok"
    return max(statuses, key=lambda s: _STATUS_SEVERITY.get(s, 0))


def _empty_capital_flow(status: str = "missing") -> dict:
    """空资金流（断源/缺失）——不伪装中性信号，data_status 标 missing/degraded。

    对齐 sentiment_context._empty_context 范式：缺失不编值，用 data_status 区分
    "无数据"与"净流入≈0 合法中性"——后者 data_status='ok' 且 signal 由实时数据算出。
    """
    return {
        "capital_flow_signal": 0.0,
        "big_fund_detected": False,
        "big_fund_type": "",
        "fund_flow_history": [],
        "data_status": status,
        "data_time": "",
    }


def _get_realtime_capital_flow(code: str) -> dict:
    """获取实时资金流数据（接入东财 push2his 资金流接口）。

    数据源：astock.stock_fund_flow_120d(code)
    返回近 120 交易日资金流，包含主力/大单/超大单净流入。

    诚实化（S111 R4）：消费 get_with_fallback_meta 元数据，断源/陈旧不再
    伪装成实时中性信号。
    - live fetch 成功（东财正典）→ data_status='ok'，正常算 signal，data_time=now
    - live fetch 成功但为新浪降级数据 → data_status='degraded'（跨源口径差异，
      关闭 #4 跨源混算伪装 ok 的毒窗口），signal 仍算（best-effort）但下游勿当东财正典
    - fetch 失败、命中陈旧缓存 → data_status='degraded'，signal=0.0（不基于
      陈旧算非零 signal），data_time=缓存时间（不戳 now 伪标刚更新）
    - fetch 失败、缓存也空 → data_status='missing'，不伪装中性 dict
    """
    try:
        from fallback import get_with_fallback_meta
        cache_key = f"capital_flow:{code}"
        history, meta = get_with_fallback_meta(
            cache_key,
            lambda: astock.stock_fund_flow_120d(code),
            ttl=600,  # 10 分钟缓存
            fallback_value=[],
        )
    except Exception:
        return _empty_capital_flow("missing")

    if not history:
        return _empty_capital_flow("missing")

    # S111 #4：检测跨源降级（新浪 vs 东财正典）——source 字段由
    # eastmoney._with_source 嵌入。含新浪降级行则标 degraded：口径与东财 f52
    # 聚合有差异，下游勿当东财正典（关闭"跨源 max_abs 混算伪装 ok"毒窗口）。
    cross_source = any(h.get("source") == "sina_fallback" for h in history)

    if meta.get("is_stale"):
        # 命中陈旧缓存：不基于陈旧数据算非零 signal，标 degraded
        cache_ts = meta.get("cache_ts")
        data_time = datetime.fromtimestamp(cache_ts).isoformat() if cache_ts else ""
        return {
            "capital_flow_signal": 0.0,
            "big_fund_detected": False,
            "big_fund_type": "",
            "fund_flow_history": [],
            "data_status": "degraded",
            "data_time": data_time,
        }

    # live fetch 成功，正常计算
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
        "data_status": "degraded" if cross_source else "ok",
        "data_time": datetime.now().isoformat(),
    }
