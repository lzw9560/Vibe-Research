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

import logging
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StormFactor:
    """单因子得分（0-100，越高=暴风雨概率越高）。"""

    name: str
    score: float  # 0-100
    detail: str
    data_status: str = "ok"  # ok | degraded | fallback_current | missing


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
    """取严格前一交易日（先退一日再用 last_trading_date 回退过周末/节假日）。

    S088 grill Q1 修：原 last_trading_date(d) 在 d 为交易日时返回 d 本身，导致
    "前一交易日"取到当日。改用 vr_paths.prev_trading_date（先 d-1 再回退）。
    """
    try:
        from vr_paths import prev_trading_date
        from datetime import datetime as _dt

        d = _dt.strptime(date, "%Y-%m-%d") if "-" in date else _dt.strptime(date, "%Y%m%d")
        return prev_trading_date(d).strftime("%Y-%m-%d")
    except Exception:
        return date


def _collect_global_factor(date: str) -> StormFactor:
    """外围隔夜因子（美股三大+A50+港股+日经+KOSPI+SOX，T-1 夜间快照）。权重 0.35。

    美股隔夜大跌 + A50 夜盘跌 → 暴风雨概率升高（A 股跟跌关联）。
    S088 Q1 daemon：读前一交易日夜间快照（get_t1_global_snapshot），无则 fallback 当前 + 标。
    S088 Q2/Q3：N225(100.N225)/KOSPI(100.KS11) 走 push2 stock/get，SOX 走 datacenter
    （RPT_INDUSTRY_INDEX/EMI00055562），三指数实测 2026-08-20 加入。
    S088 Q2 修静默失败：缺指数不再静默归零，标 missing + 权重再归一（剩余项权重÷剩余权重和），
    避免缺失项权重白给致 combined 偏向 50 中性、低估外围动量。
    权重 6 项：美股0.35/A500.20/港股0.15/日经0.10/KOSPI0.10/SOX0.10=1.0。
    """
    from strategies.storm_daemon import get_t1_global_snapshot  # noqa: PLC0415

    # 优先读前一交易日夜间快照（修历史 bug——预测交易日读前日夜间而非当日当前）
    snap = get_t1_global_snapshot(date)
    indices = (snap or {}).get("global_indices") if snap else None
    # S116：读 snapshot provenance——degraded 快照（fetch 失败/空）标 degraded，
    # 对齐下方 fallback_current 诚实范式（非 ok 假装好快照）
    data_status = "degraded" if (snap and snap.get("is_degraded")) else "ok"
    if not indices:
        # fallback 当前（无前日好快照/降级，取当前 + 标；degraded 源保留 degraded 标）
        try:
            import market  # noqa: PLC0415

            indices = market.get_global_indices() or []
            if data_status == "ok":
                data_status = "fallback_current"
        except Exception as exc:  # noqa: BLE001
            return StormFactor("外围隔夜", 50.0, f"采集失败: {exc}", "missing")

    if not indices:
        return StormFactor("外围隔夜", 50.0, "外盘数据未取得", "missing")

    by_name = {i.get("name"): i for i in indices if isinstance(i, dict)}
    us = [by_name.get(n) for n in ("道琼斯", "标普500", "纳斯达克") if by_name.get(n)]
    a50 = by_name.get("富时A50") or next(
        (i for i in indices if "富时A50" in (i.get("name") or "")), None)
    hk = [i for i in indices if "恒生" in (i.get("name") or "")]
    n225 = by_name.get("日经225") or next(
        (i for i in indices if "日经" in (i.get("name") or "")), None)
    kospi = by_name.get("韩国KOSPI") or next(
        (i for i in indices if "KOSPI" in (i.get("name") or "")), None)
    sox = by_name.get("费城半导体") or next(
        (i for i in indices if "费城" in (i.get("name") or "")), None)

    def _chg(i: dict | None) -> float | None:
        v = i.get("change_pct") if i else None
        return float(v) if isinstance(v, (int, float)) else None

    def _avg(idxs: list[dict | None]) -> float | None:
        vals = [v for v in (_chg(i) for i in idxs) if v is not None]
        return sum(vals) / len(vals) if vals else None

    # (显示名, 涨跌%, 权重)；chg=None 该项 missing，权重再归一给在场项
    items: list[tuple[str, float | None, float]] = [
        ("美股均", _avg(us), 0.35),
        ("A50", _chg(a50), 0.20),
        ("港股均", _avg(hk), 0.15),
        ("日经", _chg(n225), 0.10),
        ("KOSPI", _chg(kospi), 0.10),
        ("SOX", _chg(sox), 0.10),
    ]
    present = [(n, c, w) for n, c, w in items if c is not None]
    missing_names = [n for n, c, _ in items if c is None]
    if not present:
        return StormFactor("外围隔夜", 50.0, "外盘涨跌均未取得", "missing")
    # 权重再归一：缺失项权重重分给在场项（避免白给致低估）
    w_sum = sum(w for _, _, w in present)
    combined = sum(c * (w / w_sum) for _, c, w in present) if w_sum > 0 else 0.0
    score = max(0.0, min(100.0, 50 - combined * 15))
    # S116：src 据 data_status 分档——ok=T-1 夜间；degraded=T-1 降级已 fallback 当前；余=无 T-1 fallback
    if data_status == "ok":
        src = "T-1 夜间快照"
    elif data_status == "degraded":
        src = "T-1 degraded(fallback当前)"
    else:
        src = "当前(fallback)"
    parts = [f"{n}{c:+.2f}%" for n, c, _ in present]
    detail = f"[{src}] {' / '.join(parts)}"
    if missing_names:
        detail += f" / 缺 {','.join(missing_names)}"
    return StormFactor("外围隔夜", round(score, 1), detail, data_status)


def _load_sti_internal_signals(t1: str) -> tuple[float, float] | None:
    """读 T-1 sti_timeline 的连板高度 + 炸板率。

    S115 R3 诚实化：降级日（source_ok=0 / 列 NULL / 无行 / 查询异常）→ None，
    调用方据此标 missing + 50.0 中性基线（非 0.0+ok 假平静）。原 'if ... is not None'
    漏 NULL→保持 0.0+data_status='ok'，降级日冒充真平静→内部因子(权重0.35)
    假性偏低→风暴概率低估→suggested_position 偏高。

    source_ok=0 是写侧诚实降级标记（compute 返 dimensions=None→DB 列全 NULL）；
    source_ok NULL（旧迁移行）不阻断，由列 NULL 检查兜底，免误判好行。
    """
    try:
        import sqlite3
        from config import STI_TIMELINE_DB_PATH  # noqa: PLC0415

        _sti = sqlite3.connect(STI_TIMELINE_DB_PATH)
        _sti.row_factory = sqlite3.Row
        try:
            row = _sti.execute(
                "SELECT dimension_max_boards, raw_break_rate, source_ok "
                "FROM sti_timeline WHERE date=?",
                (t1,),
            ).fetchone()
            if row is None:
                return None
            if row["source_ok"] == 0:
                return None
            max_boards = row["dimension_max_boards"]
            break_rate = row["raw_break_rate"]
            if max_boards is None or break_rate is None:
                return None
            return float(max_boards), float(break_rate)
        finally:
            _sti.close()
    except Exception as e:  # noqa: BLE001 — sti 缺失/异常 → 诚实降级 missing（不臆造 0.0）
        logging.getLogger("storm_predictor").warning(
            "_load_sti_internal_signals(t1=%s) STI 取数失败，降级 missing: %s", t1, e
        )
        return None


def _collect_internal_factor(date: str) -> StormFactor:
    """前日内部先行因子（连板梯队高度/炸板率/溢价）。权重 0.40。

    情绪高潮→崩盘先行信号：连板高度见顶 + 炸板率上升 + 溢价转负。
    数据：T-1 gene_scores + sti_timeline（max_boards/break_rate）。
    """
    try:
        from limitup_screener.data import load_gene_scores  # noqa: PLC0415

        t1 = _prev_trading_day(date)
        genes = load_gene_scores(t1) or []
        if not genes:
            return StormFactor("前日内部先行", 50.0, f"T-1({t1}) gene_scores 未取得", "missing")

        avg_seal = sum(g.factors.get("封板率", 0) or 0 for g in genes) / len(genes)
        avg_rebound = sum(g.factors.get("炸板后溢价", 0) or 0 for g in genes) / len(genes)

        # sti_timeline T-1 的连板高度 + 炸板率
        # S088 R10 分析修：sti_timeline 在 STI_TIMELINE_DB_PATH（非 gene_scores DB），
        # 原调 limitup_screener.data.get_db()（gene_scores DB）→ no such table → 恒降级 0。
        # S115 R3：降级日（source_ok=0 / 列 NULL / 无行）→ None → missing + 50.0（非 0.0+ok 假平静）。
        sti_signals = _load_sti_internal_signals(t1)
        if sti_signals is None:
            return StormFactor(
                "前日内部先行", 50.0,
                f"T-1({t1}) STI 降级/缺行（连板高度/炸板率未知）", "missing",
            )
        max_boards, break_rate = sti_signals

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
    """新闻利空/利好对比（newsradar 盘后，前一交易日夜间快照）。权重 0.20。

    S088 grill Q5：原 radar.get("items") 取不存在的顶层键致因子恒 missing、0.20 权重失效；
    fetch_radar 顶层是 industries 嵌套 items（无顶层 items 键），须扁平化聚合。
    S088 R10 深度分析（2026-08-20，4 视角对抗）：口径对齐 _collect_global_factor——优先读
    前一交易日夜间快照的 news_items（storm_daemon 已扁平化存入，原 orphaned 死写无读者，
    现接线），无快照 fallback 当前 newsradar cache + 标 fallback_current。闭合"用今日新闻
    预测历史日"违 A7/§1.2 可复现 bug。加利好对冲：强情绪复合词 + 占比口径（非差值）避免
    总量膨胀失真。不臆造、缺数据标 missing。
    """
    from strategies.storm_daemon import get_t1_global_snapshot  # noqa: PLC0415

    # 优先读前一交易日夜间快照的 news_items（daemon 已扁平化，对齐 global 口径）
    snap = get_t1_global_snapshot(date)
    items = (snap or {}).get("news_items") if snap else None
    data_status = "ok"
    src = "T-1 夜间快照"
    if not items:
        # fallback 当前 newsradar cache（无前日快照，标 fallback_current）
        try:
            import newsradar  # noqa: PLC0415

            radar = newsradar.get_radar(force=False) or {}
            # fetch_radar 顶层是 industries 嵌套 items（无顶层 items 键）；扁平化聚合
            items = (
                [it for ind in (radar.get("industries", []) or [])
                 for it in (ind.get("items", []) or [])]
                if isinstance(radar, dict) else []
            )
            data_status = "fallback_current"
            src = "当前(fallback)"
        except Exception as exc:  # noqa: BLE001
            return StormFactor("新闻密度", 50.0, f"采集失败: {exc}", "missing")

    if not items:
        return StormFactor("新闻密度", 50.0, "新闻未取得", "missing")

    bearish_kw = ["暴跌", "崩盘", "跌停", "退市", "爆雷", "违约", "大利空", "重挫", "闪崩", "熔断"]
    bullish_kw = ["涨停", "大涨", "暴涨", "突破新高", "超预期", "大订单", "增持", "回购", "大利好"]

    def _text(it: dict) -> str:
        return str(it.get("title", "")) + str(it.get("summary", ""))

    bearish_count = sum(1 for it in items if any(k in _text(it) for k in bearish_kw))
    bullish_count = sum(1 for it in items if any(k in _text(it) for k in bullish_kw))

    total = bearish_count + bullish_count
    if total == 0:
        return StormFactor(
            "新闻密度", 50.0,
            f"[{src}] 总 {len(items)} 条 / 无强情绪词命中", "missing",
        )
    # 利空占比 → 分（利空越多概率越高）；占比口径非差值，免总量膨胀失真
    ratio = bearish_count / total
    score = ratio * 100.0
    detail = f"[{src}] 总 {len(items)} 条 / 利空 {bearish_count} / 利好 {bullish_count} / 利空占比 {ratio:.0%}"
    return StormFactor("新闻密度", round(score, 1), detail, data_status)


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
