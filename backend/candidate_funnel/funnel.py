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
from candidate_funnel.sources.catalyst import classify_announcement
from candidate_funnel.thresholds import resolve_thresholds


# S044 R6：漏斗阶段 → 特征 stage 映射。look-ahead 防护——sources 在当前 stage 取数，
# availability_offset=1 的北向/龙虎榜缺数据标 missing 保留不过滤（见 _filter_r2 北向 None 保留）。
_STAGE_MAP: dict[str, str] = {"pre_market": "s1", "auction": "s3"}


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
    codes: list[str], activity: dict[str, dict], eff, fund: dict[str, dict] | None = None,
) -> tuple[list[str], list[FilterRecord]]:
    """R2 收敛：按生效阈值剔除冷股（换手 < turnover_cold）+ 北向绝对值过滤（S044 R5）。

    北向用非方向占位口径：abs(northbound) < northbound_abs_min 剔除（筛掉无北向动作的票，
    方向判断留给后续主力净流/龙虎榜组合判断）。northbound 缺失（None）保留不过滤（grill Q9：
    不因缺数据过滤掉）。northbound_abs_min 默认 0 → abs>=0 永不命中 → 等价有北向数据即保留。
    阈值标注「基于交易经验，未经历史回测验证」（回测由 S041/S043 承担）。
    """
    kept: list[str] = []
    filtered: list[FilterRecord] = []
    fund = fund or {}
    for c in codes:
        a = activity.get(c, {})
        t = a.get("turnover_pct")
        name = a.get("name", c)
        if t is None:
            filtered.append(FilterRecord(code=c, name=name, reason="换手未取得，剔除"))
            continue
        if t < eff.turnover_cold:
            filtered.append(FilterRecord(code=c, name=name, reason=f"换手{t}%<{eff.turnover_cold}%"))
            continue
        nb = (fund.get(c, {}) or {}).get("northbound")
        if nb is not None and abs(nb) < eff.northbound_abs_min:
            filtered.append(FilterRecord(code=c, name=name, reason=f"北向|{nb}|<{eff.northbound_abs_min}万"))
            continue
        kept.append(c)
    return kept, filtered


def _resolve_name(
    code: str,
    genes: dict[str, dict],
    activity: dict[str, dict],
    auction: dict[str, dict],
    catalyst: dict[str, dict],
) -> str:
    """按 genes→activity→auction→catalyst 顺序解析股票名，均缺则回退 code。

    R3 层 auction/catalyst 常不带头名（仅竞价/催化数据的票才有），
    需回退到 R1/R2 已采集的 genes/activity，避免 name 退化成 code（S028 R3）。
    """
    return (
        genes.get(code, {}).get("name")
        or activity.get(code, {}).get("name")
        or auction.get(code, {}).get("name")
        or catalyst.get(code, {}).get("name")
        or code
    )


def _r3_triggers(code: str, auction: dict[str, dict], catalyst: dict[str, dict]) -> list[str]:
    """R3 触发类型（竞价异动/公告催化/概念联动）——与 _filter_r3 判定一致，供前端多选筛选（S045 R2）。"""
    triggers: list[str] = []
    if auction.get(code, {}).get("auction_open_pct") is not None:
        triggers.append("竞价异动")
    cat = catalyst.get(code, {})
    if cat.get("announcements"):
        triggers.append("公告催化")
    if cat.get("concepts"):
        triggers.append("概念联动")
    return triggers


def _filter_r3(
    codes: list[str], auction: dict[str, dict], catalyst: dict[str, dict],
    genes: dict[str, dict], activity: dict[str, dict],
    ann_types: list[str] | None = None,
) -> tuple[list[str], list[FilterRecord]]:
    """R3 定稿：保留有竞价异动或公告催化的标的。

    ann_types 非空时进一步要求至少一条公告类型命中（预增/重组/回购）——
    即便有竞价/概念催化，公告类型不匹配也过滤（用户显式按类型筛时的严格口径）。
    默认 None 向后兼容（不按类型筛，仅判有无催化）。
    """
    kept: list[str] = []
    filtered: list[FilterRecord] = []
    for c in codes:
        has_auction = bool(auction.get(c, {}).get("auction_open_pct") is not None)
        cat = catalyst.get(c, {})
        has_catalyst = bool(cat.get("announcements") or cat.get("concepts"))
        if not (has_auction or has_catalyst):
            name = _resolve_name(c, genes, activity, auction, catalyst)
            filtered.append(FilterRecord(code=c, name=name, reason="无竞价异动/公告催化"))
            continue
        if ann_types:
            cat_anns = cat.get("announcements") or []
            if not any(classify_announcement(a) in ann_types for a in cat_anns):
                name = _resolve_name(c, genes, activity, auction, catalyst)
                filtered.append(FilterRecord(code=c, name=name, reason=f"公告类型不在{ann_types}"))
                continue
        kept.append(c)
    return kept, filtered


def run_funnel(stage: str, date: str, cfg: ThresholdConfig) -> FunnelResult:
    """R1→R2→R3 + 自选并行；返回 FunnelResult。"""
    as_of = datetime.now()
    phase = _fetch_sentiment_phase(date)
    eff = resolve_thresholds(cfg, phase)
    # 情绪档位标注（conditions 复用）
    phase_note = f"情绪档位={phase or '未取得'}" if phase else "情绪档位未取得，沿用基数"
    current_stage = _STAGE_MAP.get(stage, "s1")
    base_conditions = [
        f"换手冷档={eff.turnover_cold}%",
        f"换手热档={eff.turnover_hot}%",
        f"量比活跃线={eff.vol_ratio_active}",
        f"成交额下限={eff.amount_yi_min}亿",
        f"数据阶段={current_stage}（offset=1 北向/龙虎榜缺数据标 missing 保留）",
        phase_note,
    ]

    # ---- R1 宽源 ----
    r1_data_status: str | None = None
    r1_data_reason: str | None = None
    try:
        genes = sources.gene.fetch_genes(date)
        board = sources.board_ladder.fetch_board_ladder(date)
    except Exception as exc:  # noqa: BLE001 — 采集失败标记层，不静默返空（S023 C2）
        genes, board = {}, {}
        r1_data_status = "未取得"
        r1_data_reason = f"R1 宽源采集失败: {exc}"
    r1_input = list(genes.keys())
    r1_kept, r1_filtered = _filter_r1(r1_input, genes)
    r1 = FunnelLayer(
        layer_id="R1", name="宽源", as_of=as_of,
        input_count=len(r1_input), output_count=len(r1_kept),
        filtered_out=r1_filtered, output_codes=r1_kept,
        conditions=["涨停基因得分筛选", "连板梯队（含炸板/昨涨停今表现）", *base_conditions],
        passed=[{"code": c, "name": genes.get(c, {}).get("name", c), "gene_score": genes.get(c, {}).get("gene_score")} for c in r1_kept],
        data_status=r1_data_status, data_reason=r1_data_reason,
    )
    layers: list[FunnelLayer] = [r1]

    # ---- R2 收敛 ----
    r2_data_status: str | None = None
    r2_data_reason: str | None = None
    try:
        activity = sources.activity.fetch_activity(r1_kept, date)
        fund = sources.fund_flow.fetch_fund_flow(r1_kept, date)
    except Exception as exc:  # noqa: BLE001 — 采集失败标记层（S023 C2）
        activity, fund = {}, {}
        r2_data_status = "未取得"
        r2_data_reason = f"R2 收敛采集失败: {exc}"
    r2_kept, r2_filtered = _filter_r2(r1_kept, activity, eff, fund)
    r2 = FunnelLayer(
        layer_id="R2", name="收敛", as_of=as_of,
        input_count=len(r1_kept), output_count=len(r2_kept),
        filtered_out=r2_filtered, output_codes=r2_kept,
        conditions=[f"换手>={eff.turnover_cold}%（{phase_note}）", *base_conditions],
        passed=[{"code": c, "name": activity.get(c, {}).get("name", c), "gene_score": genes.get(c, {}).get("gene_score")} for c in r2_kept],
        data_status=r2_data_status, data_reason=r2_data_reason,
    )
    layers.append(r2)

    # ---- R3 定稿 ----
    r3_data_status: str | None = None
    r3_data_reason: str | None = None
    try:
        auction = sources.auction.fetch_auction(date)
        catalyst = sources.catalyst.fetch_catalyst(r2_kept, date)
    except Exception as exc:  # noqa: BLE001 — 采集失败标记层（S023 C2）
        auction, catalyst = {}, {}
        r3_data_status = "未取得"
        r3_data_reason = f"R3 定稿采集失败: {exc}"
    r3_kept, r3_filtered = _filter_r3(r2_kept, auction, catalyst, genes, activity)
    r3 = FunnelLayer(
        layer_id="R3", name="定稿", as_of=as_of,
        input_count=len(r2_kept), output_count=len(r3_kept),
        filtered_out=r3_filtered, output_codes=r3_kept,
        conditions=["集合竞价异动 OR 公告催化 OR 板块联动", *base_conditions],
        passed=[
            {"code": c, "name": _resolve_name(c, genes, activity, auction, catalyst),
             "gene_score": genes.get(c, {}).get("gene_score"),
             "matched_triggers": _r3_triggers(c, auction, catalyst)}
            for c in r3_kept
        ],
        data_status=r3_data_status, data_reason=r3_data_reason,
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
