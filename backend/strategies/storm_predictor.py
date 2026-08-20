# -*- coding: utf-8 -*-
"""S088 盘前暴风雨预测模型——独立于事后 STI 检测。

盘前用外围隔夜（美股+A50+港股）+ 前日内部先行（连板高度/炸板率/溢价）+ 新闻密度，
算暴风雨概率分(0-100) + 推荐仓位。跟事后 STI（盘后检测）互补：盘前预测 + 盘后验证。

诚实边界：暴风雨纯预测不可行（黑天鹅不可测），本模型是"条件积累监测"——
外围大跌 + 内部情绪转弱 + 利空新闻密度 → 暴风雨概率升高，产出概率分 + 仓位前置，
非 100% 预测。数据源全用现有（get_global_indices/gene_scores/newsradar），
衍生品(VIX/期权/期货)先跳过，估值水位 R4 先跳过（数据源待定，不臆造）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StormFactor:
    """单因子得分（0-100，越高=暴风雨概率越高）。"""

    name: str
    score: float  # 0-100
    detail: str
    data_status: str = "ok"  # ok | missing


@dataclass(frozen=True)
class StormPrediction:
    """盘前暴风雨预测结果。"""

    date: str
    probability: float  # 0-100
    risk_level: str  # 低/中/高/极高
    suggested_position: float  # 0-1 推荐仓位比例
    factors: list[StormFactor] = field(default_factory=list)
    disclaimer: str = "概率预测非确定，市场有风险，黑天鹅不可测"


# 概率分 → 风险等级 + 仓位映射（spec §5.2）
def _probability_to_level(p: float) -> tuple[str, float]:
    if p >= 70:
        return "极高", 0.25
    if p >= 50:
        return "高", 0.50
    if p >= 30:
        return "中", 0.70
    return "低", 1.0


def _prev_trading_day(date: str) -> str:
    """取前一交易日（复用 vr_paths.last_trading_date，做节假日判断）。"""
    try:
        from vr_paths import last_trading_date
        from datetime import datetime as _dt

        d = _dt.strptime(date, "%Y-%m-%d") if "-" in date else _dt.strptime(date, "%Y%m%d")
        return last_trading_date(d).strftime("%Y-%m-%d")
    except Exception:
        return date


def _collect_global_factor(date: str) -> StormFactor:
    """外围隔夜因子（美股三大 + A50 + 港股）。权重 0.40。

    美股隔夜大跌 + A50 夜盘跌 → 暴风雨概率升高（A 股跟跌关联）。
    """
    try:
        import market  # noqa: PLC0415

        indices = market.get_global_indices() or []
        if not indices:
            return StormFactor("外围隔夜", 50.0, "外盘数据未取得", "missing")

        us = [i for i in indices if i.get("name") in ("道琼斯", "标普500", "纳斯达克")]
        a50 = next((i for i in indices if "富时A50" in (i.get("name") or "")), None)
        hk = [i for i in indices if "恒生" in (i.get("name") or "")]

        us_avg = sum(float(i.get("change_pct") or 0) for i in us) / max(len(us), 1)
        a50_chg = float(a50.get("change_pct") or 0) if a50 else 0.0
        hk_avg = sum(float(i.get("change_pct") or 0) for i in hk) / max(len(hk), 1)

        # 综合涨跌 → 概率分（跌 0% = 50 中性，跌 2% = 80 高，涨 2% = 20 低）
        combined = us_avg * 0.5 + a50_chg * 0.3 + hk_avg * 0.2
        score = max(0.0, min(100.0, 50 - combined * 15))
        detail = f"美股均 {us_avg:+.2f}% / A50 {a50_chg:+.2f}% / 港股均 {hk_avg:+.2f}%"
        return StormFactor("外围隔夜", round(score, 1), detail)
    except Exception as exc:  # noqa: BLE001
        return StormFactor("外围隔夜", 50.0, f"采集失败: {exc}", "missing")


def _collect_internal_factor(date: str) -> StormFactor:
    """前日内部先行因子（连板梯队高度/炸板率/溢价）。权重 0.40。

    情绪高潮→崩盘先行信号：连板高度见顶 + 炸板率上升 + 溢价转负。
    数据：T-1 gene_scores + sti_timeline（max_boards/break_rate）。
    """
    try:
        from limitup_screener.data import load_gene_scores, get_db  # noqa: PLC0415

        t1 = _prev_trading_day(date)
        genes = load_gene_scores(t1) or []
        if not genes:
            return StormFactor("前日内部先行", 50.0, f"T-1({t1}) gene_scores 未取得", "missing")

        avg_seal = sum(g.factors.get("封板率", 0) or 0 for g in genes) / len(genes)
        avg_rebound = sum(g.factors.get("炸板后溢价", 0) or 0 for g in genes) / len(genes)

        # sti_timeline T-1 的连板高度 + 炸板率
        max_boards = 0.0
        break_rate = 0.0
        try:
            db = get_db()
            row = db.execute(
                "SELECT dimension_max_boards, raw_break_rate FROM sti_timeline WHERE date=?",
                (t1,),
            ).fetchone()
            if row and row["dimension_max_boards"] is not None:
                max_boards = float(row["dimension_max_boards"])
            if row and row["raw_break_rate"] is not None:
                break_rate = float(row["raw_break_rate"])
        except Exception:  # noqa: BLE001 — sti 缺失降级 0
            pass

        # 情绪转弱信号 → 暴风雨概率
        # 连板高度（>5 见顶信号）+ 炸板率（>20% 转弱）+ 溢价（<0 转负）
        height_score = min(100.0, max_boards * 15)  # 5板=75, 7板=100
        break_score = min(100.0, break_rate * 200)  # 20%炸板=40, 40%=80
        rebound_score = max(0.0, min(100.0, 50 - avg_rebound * 2))  # 溢价<0 → 高分
        score = (height_score + break_score + rebound_score) / 3

        detail = f"连板 {max_boards:.0f}板 / 炸板率 {break_rate:.0%} / 炸板后溢价 {avg_rebound:.1f} / 封板率 {avg_seal:.0f}%"
        return StormFactor("前日内部先行", round(score, 1), detail)
    except Exception as exc:  # noqa: BLE001
        return StormFactor("前日内部先行", 50.0, f"采集失败: {exc}", "missing")


def _collect_news_factor(date: str) -> StormFactor:
    """新闻密度辅助（newsradar 盘后利空数量）。权重 0.20。

    利空关键词密度 → 暴风雨概率加分（不先做 NLP 情绪量化）。
    """
    try:
        import newsradar  # noqa: PLC0415

        radar = newsradar.get_radar(force=False) or {}
        items = radar.get("items", []) if isinstance(radar, dict) else []
        if not items:
            return StormFactor("新闻密度", 50.0, "新闻未取得", "missing")

        bearish_kw = ["跌", "崩", "雷", "退市", "监管", "处罚", "下滑", "亏损", "利空", "风险", "爆", "违约"]
        bearish_count = sum(
            1
            for it in items
            if any(k in (str(it.get("title", "")) + str(it.get("summary", ""))) for k in bearish_kw)
        )
        # 利空密度 → 分（>10 利空 = 高概率，<3 = 低）
        score = min(100.0, bearish_count * 8)
        detail = f"总 {len(items)} 条 / 利空 {bearish_count} 条"
        return StormFactor("新闻密度", round(score, 1), detail)
    except Exception as exc:  # noqa: BLE001
        return StormFactor("新闻密度", 50.0, f"采集失败: {exc}", "missing")


def _collect_calendar_factor(date: str) -> StormFactor:
    """日历事件风险（交割日 + 月末）。辅助加分。

    50ETF/300ETF 期权交割日（每月第4周三）+ 股指期货交割日（每月第3周五）→ 交割日±1 波动加剧。
    月末资金面季节性。固定日历可算，不需数据源。
    """
    try:
        from datetime import datetime as _dt, date as _date

        d = _dt.strptime(date, "%Y-%m-%d") if "-" in date else _dt.strptime(date, "%Y%m%d")

        def _nth_weekday(year: int, month: int, weekday: int, n: int) -> _date:
            first = _date(year, month, 1)
            offset = (weekday - first.weekday()) % 7
            return first.replace(day=1 + offset + (n - 1) * 7)

        opt_day = _nth_weekday(d.year, d.month, 2, 4)  # 期权交割日：第4周三
        fut_day = _nth_weekday(d.year, d.month, 4, 3)  # 期货交割日：第3周五
        is_delivery = abs((d.date() - opt_day).days) <= 1 or abs((d.date() - fut_day).days) <= 1
        is_month_end = d.day >= 28

        if is_delivery:
            score = 80.0
            detail = f"交割日±1（期权{opt_day:%m-%d}/期货{fut_day:%m-%d}）波动加剧"
        elif is_month_end:
            score = 60.0
            detail = "月末资金面季节性"
        else:
            score = 30.0
            detail = f"非交割日（期权{opt_day:%m-%d}/期货{fut_day:%m-%d}）"
        return StormFactor("日历事件", score, detail)
    except Exception as exc:  # noqa: BLE001
        return StormFactor("日历事件", 50.0, f"计算失败: {exc}", "missing")


def predict_storm(date: str | None = None) -> StormPrediction:
    """盘前暴风雨预测主函数。

    Args:
        date: T 日期（YYYY-MM-DD），默认今日。

    Returns:
        StormPrediction：概率分(0-100) + 风险等级 + 仓位建议 + 因子明细。
    """
    from datetime import datetime as _dt

    d = date or _dt.now().strftime("%Y-%m-%d")

    # 因子采集
    global_f = _collect_global_factor(d)
    internal_f = _collect_internal_factor(d)
    news_f = _collect_news_factor(d)
    calendar_f = _collect_calendar_factor(d)

    # 加权（外围 0.35 + 内部 0.35 + 新闻 0.20 + 日历 0.10；估值 R4 先跳过）
    probability = (
        global_f.score * 0.35
        + internal_f.score * 0.35
        + news_f.score * 0.20
        + calendar_f.score * 0.10
    )
    probability = round(max(0.0, min(100.0, probability)), 1)

    risk_level, suggested_position = _probability_to_level(probability)

    return StormPrediction(
        date=d,
        probability=probability,
        risk_level=risk_level,
        suggested_position=suggested_position,
        factors=[global_f, internal_f, news_f, calendar_f],
    )
