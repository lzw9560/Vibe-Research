# -*- coding: utf-8 -*-
"""漏斗编排（S002 B9）：R1→R2→R3 + 自选并行。

每层输出为下轮输入；任一层空则下游无输入并提示（AC9）。
R2 按生效阈值过滤冷股；R3 按竞价/催化过滤。最终候选构建诊断卡。
"""

from __future__ import annotations

from datetime import datetime

from candidate_funnel import sources
from candidate_funnel.diagnosis import build_diagnosis_card, build_indicator_set
from candidate_funnel.models import (
    FilterRecord,
    FunnelLayer,
    FunnelResult,
    IndicatorSet,
    ThresholdConfig,
)
from candidate_funnel.sources._filters import classify_exclusion
from candidate_funnel.thresholds import resolve_thresholds


def _fetch_sentiment_phase(date: str) -> str | None:
    """取当日情绪 phase（weather_state）。取不到返回 None（→ 阈值降级基数）。"""
    try:
        from routers import sentiment_weather as sw
        data = sw.get_weather_latest()
        if hasattr(data, "__awaitable__"):
            return None  # 异步处理器不在此同步调用，降级
        return (data or {}).get("data", {}).get("weather_state")
    except Exception:
        return None


def _filter_r1(codes: list[str], genes: dict[str, dict]) -> tuple[list[str], list[FilterRecord]]:
    kept: list[str] = []
    filtered: list[FilterRecord] = []
    for c in codes:
        name = genes.get(c, {}).get("name", c)
        excluded, reason = classify_exclusion(name, c)
        if excluded:
            filtered.append(FilterRecord(code=c, name=name, reason=reason or "剔除"))
        else:
            kept.append(c)
    return kept, filtered


def _filter_r2(
    codes: list[str], activity: dict[str, dict], eff
) -> tuple[list[str], list[FilterRecord]]:
    """R2 收敛：按生效阈值剔除冷股（换手 < turnover_cold）。"""
    kept: list[str] = []
    filtered: list[FilterRecord] = []
    for c in codes:
        a = activity.get(c, {})
        t = a.get("turnover_pct")
        name = a.get("name", c)
        if t is None:
            filtered.append(FilterRecord(code=c, name=name, reason="换手未取得，剔除"))
        elif t < eff.turnover_cold:
            filtered.append(FilterRecord(code=c, name=name, reason=f"换手{t}%<{eff.turnover_cold}%"))
        else:
            kept.append(c)
    return kept, filtered


def _filter_r3(
    codes: list[str], auction: dict[str, dict], catalyst: dict[str, dict]
) -> tuple[list[str], list[FilterRecord]]:
    """R3 定稿：保留有竞价异动或公告催化的标的。"""
    kept: list[str] = []
    filtered: list[FilterRecord] = []
    for c in codes:
        has_auction = bool(auction.get(c, {}).get("auction_open_pct") is not None)
        cat = catalyst.get(c, {})
        has_catalyst = bool(cat.get("announcements") or cat.get("concepts"))
        if has_auction or has_catalyst:
            kept.append(c)
        else:
            name = (auction.get(c, {}).get("name") or c)
            filtered.append(FilterRecord(code=c, name=name, reason="无竞价异动/公告催化"))
    return kept, filtered


def run_funnel(stage: str, date: str, cfg: ThresholdConfig) -> FunnelResult:
    """R1→R2→R3 + 自选并行；返回 FunnelResult。"""
    as_of = datetime.now()
    phase = _fetch_sentiment_phase(date)
    eff = resolve_thresholds(cfg, phase)

    # ---- R1 宽源 ----
    genes = sources.gene.fetch_genes(date)
    board = sources.board_ladder.fetch_board_ladder(date)
    r1_input = list(genes.keys())
    r1_kept, r1_filtered = _filter_r1(r1_input, genes)
    r1 = FunnelLayer(
        layer_id="R1", name="宽源", as_of=as_of,
        input_count=len(r1_input), output_count=len(r1_kept),
        filtered_out=r1_filtered, output_codes=r1_kept,
    )
    layers: list[FunnelLayer] = [r1]

    # ---- R2 收敛 ----
    activity = sources.activity.fetch_activity(r1_kept, date)
    fund = sources.fund_flow.fetch_fund_flow(r1_kept, date)
    r2_kept, r2_filtered = _filter_r2(r1_kept, activity, eff)
    r2 = FunnelLayer(
        layer_id="R2", name="收敛", as_of=as_of,
        input_count=len(r1_kept), output_count=len(r2_kept),
        filtered_out=r2_filtered, output_codes=r2_kept,
    )
    layers.append(r2)

    # ---- R3 定稿 ----
    auction = sources.auction.fetch_auction(date)
    catalyst = sources.catalyst.fetch_catalyst(r2_kept, date)
    r3_kept, r3_filtered = _filter_r3(r2_kept, auction, catalyst)
    r3 = FunnelLayer(
        layer_id="R3", name="定稿", as_of=as_of,
        input_count=len(r2_kept), output_count=len(r3_kept),
        filtered_out=r3_filtered, output_codes=r3_kept,
    )
    layers.append(r3)

    # ---- 自选/手动并行 ----
    wl = sources.watchlist_in.get_watchlist_codes()
    self_layer = FunnelLayer(
        layer_id="SELF", name="自选/手动", as_of=as_of,
        input_count=len(wl), output_count=len(wl),
        filtered_out=[], output_codes=list(wl),
    )
    layers.append(self_layer)

    # ---- 最终候选 = R3 输出 ∪ 自选 ----
    final_codes = list(dict.fromkeys(r3_kept + list(wl)))
    cards = []
    for code in final_codes:
        name = (
            genes.get(code, {}).get("name")
            or activity.get(code, {}).get("name")
            or auction.get(code, {}).get("name")
            or code
        )
        ind = build_indicator_set(code, name, genes, activity, fund, auction, catalyst, board)
        cards.append(build_diagnosis_card(code, name, ind, eff, market_ctx=board, as_of=as_of))

    return FunnelResult(
        run_id=f"run-{date}-{stage}",
        date=date,
        layers=layers,
        final_candidates=cards,
        threshold_config=cfg,
        sentiment_phase=phase,
        as_of=as_of,
    )


def diagnose(code: str, date: str, cfg: ThresholdConfig) -> DiagnosisCard:
    """构建单只股票诊断卡（E3 GET /candidates/{code}/diagnosis 用）。"""
    as_of = datetime.now()
    phase = _fetch_sentiment_phase(date)
    eff = resolve_thresholds(cfg, phase)
    genes = sources.gene.fetch_genes(date)
    board = sources.board_ladder.fetch_board_ladder(date)
    activity = sources.activity.fetch_activity([code], date)
    fund = sources.fund_flow.fetch_fund_flow([code], date)
    auction = sources.auction.fetch_auction(date)
    catalyst = sources.catalyst.fetch_catalyst([code], date)
    name = (
        genes.get(code, {}).get("name")
        or activity.get(code, {}).get("name")
        or code
    )
    ind = build_indicator_set(code, name, genes, activity, fund, auction, catalyst, board)
    return build_diagnosis_card(code, name, ind, eff, market_ctx=board, as_of=as_of)
