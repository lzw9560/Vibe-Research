# -*- coding: utf-8 -*-
"""漏斗编排（S002 B9 / S084 R1-only）：R1 宽源 + 自选并行。

S084 TASK A：选股池 R1-only——R2/R3 过滤已下放战法层，本层仅展示全量候选
（data_status 标「已下放战法」）。final_candidates = R1 全涨停 ∪ 自选，不再经 R2/R3 收敛。
R2/R3 的 _filter_r2/_filter_r3 函数保留供战法层与单测调用（diagnose 不依赖）。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from sentiment_context import SentimentContext


# S044 R6：漏斗阶段 → 特征 stage 映射。look-ahead 防护——sources 在当前 stage 取数，
# availability_offset=1 的北向/龙虎榜缺数据标 missing 保留不过滤（见 _filter_r2 北向 None 保留）。
_STAGE_MAP: dict[str, str] = {"pre_market": "s1", "auction": "s3"}


def _fetch_sentiment_phase(date: str, ctx: "SentimentContext | None" = None) -> str | None:
    """取当日情绪 phase（weather_state）。取不到返回 None（→ 阈值降级基数）。

    S063 T5：优先从管线头部下传的 SentimentContext 取（一次采集逐级下传）；
    ctx=None 或 ctx.weather_state=None 时降级到旧路径（独立调 sentiment_weather）。
    旧路径保留供未接 ctx 的调用方（topology、diagnose 独立诊断）。
    """
    if ctx is not None and ctx.weather_state:
        return ctx.weather_state
    try:
        from routers import sentiment_weather as sw
        data = sw.get_weather_latest()
        if hasattr(data, "__awaitable__"):
            return None  # 异步处理器不在此同步调用，降级
        return (data or {}).get("data", {}).get("weather_state")
    except Exception:
        return None


# S049 D6：run_funnel (date,config) TTL 缓存——_collect（因子）与 _build_funnel_layers（漏斗）
# 各跑一遍会重复外部请求；缓存命中即复用。rerun 不受影响（done 即清）。
# S004 R5：TTL 接线 config.CANDIDATE_FUNNEL_CACHE_TTL（默认 3600s，盘后预计算长 TTL）。
_FUNNEL_CACHE: dict[str, tuple[float, "FunnelResult"]] = {}


def _funnel_cache_ttl() -> int:
    """从 config 读 TTL（惰性，避免模块导入时 config 未就绪）。"""
    try:
        from config import default_config
        return int(getattr(default_config, "CANDIDATE_FUNNEL_CACHE_TTL", 3600))
    except Exception:
        return 3600


def _funnel_cache_key(date: str, cfg: ThresholdConfig) -> str:
    """缓存键=date + config 排序 JSON（防不同阈值串数据）。"""
    import json
    cfg_dict = cfg.model_dump(mode="json")
    return f"{date}|{json.dumps(cfg_dict, sort_keys=True, ensure_ascii=False)}"


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


def _top_n_by_gene_score(codes: list[str], genes: dict[str, dict], n: int) -> list[str]:
    """S004 R3：按 gene_score 降序取前 N 候选（top-N 限界，不引入新排序口径）。

    gene_score 缺失/None 按 0 处理；同分按 code 字典序稳定排序。
    n<=0 或 codes 不足 n 时返 codes 全量（不截断）。
    """
    if n <= 0 or len(codes) <= n:
        return list(codes)
    def _score(c: str) -> float:
        g = genes.get(c, {})
        s = g.get("gene_score")
        return float(s) if s is not None else 0.0
    return sorted(codes, key=lambda c: (-_score(c), c))[:n]


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


def _consec_boards_for(code: str, board: dict) -> int | None:
    """从 board.lianban_stocks 按 code 匹配个股连板数（与 build_indicator_set 同口径）。"""
    for s in (board or {}).get("lianban_stocks", []):
        if isinstance(s, dict) and s.get("code") == code:
            return s.get("boards")
    return None


def _catalyst_summary(code: str, catalyst: dict[str, dict]) -> str | None:
    """催化摘要：公告标题首条 + 概念名（前端矩阵列展示用）。无催化返 None。"""
    cat = catalyst.get(code, {})
    anns = cat.get("announcements") or []
    concepts = cat.get("concepts") or []
    parts: list[str] = []
    if anns:
        parts.append(anns[0].get("title", "") if isinstance(anns[0], dict) else str(anns[0]))
    if concepts:
        parts.append("/".join(concepts[:3]))
    return "；".join(parts) if parts else None


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


def run_funnel(stage: str, date: str, cfg: ThresholdConfig, ctx: "SentimentContext | None" = None) -> FunnelResult:
    """R1→R2→R3 + 自选并行；返回 FunnelResult。

    S063 T5：可选 ctx 参数——管线头部 SentimentContext 一次采集逐级下传。
    ctx 提供 weather_state（替代 _fetch_sentiment_phase 独立调）+ source_date。

    S049 D6：(date,config) TTL 缓存——_collect（因子）与 _build_funnel_layers（漏斗）
    各跑一遍会重复外部请求；命中缓存即复用。rerun 走 run_funnel_force（清缓存路径）。

    注意：ctx 不参与缓存键——同日同 config 的 weather_state 应一致（T-1 硬标准），
    若 T-1 情绪数据（weather_state）改了，应走 run_funnel_force 清缓存（S072：STI 不再调 R2 阈值，仅 weather_state 软标注）。
    """
    import time
    key = _funnel_cache_key(date, cfg)
    now = time.time()
    hit = _FUNNEL_CACHE.get(key)
    if hit and now - hit[0] < _funnel_cache_ttl():
        return hit[1]
    result = _run_funnel_impl(stage, date, cfg, ctx)
    _FUNNEL_CACHE[key] = (now, result)
    return result


def run_funnel_force(stage: str, date: str, cfg: ThresholdConfig, ctx: "SentimentContext | None" = None) -> FunnelResult:
    """rerun 显式清缓存路径（不受 TTL 缓存影响）。"""
    import time
    key = _funnel_cache_key(date, cfg)
    _FUNNEL_CACHE.pop(key, None)
    result = _run_funnel_impl(stage, date, cfg, ctx)
    _FUNNEL_CACHE[key] = (time.time(), result)
    return result


def clear_funnel_cache(date: str | None = None) -> None:
    if date is None:
        _FUNNEL_CACHE.clear()
        return
    for k in [k for k in _FUNNEL_CACHE if k.startswith(f"{date}|")]:
        _FUNNEL_CACHE.pop(k, None)


def _run_funnel_impl(stage: str, date: str, cfg: ThresholdConfig, ctx: "SentimentContext | None" = None) -> FunnelResult:
    """R1→R2→R3 + 自选并行实现（无缓存，由 run_funnel 包裹缓存）。

    S063 T5：ctx 优先——管线头部 SentimentContext 下传 weather_state + source_date。
    S004 R3：R2 采集前按 gene_score 降序取 top-N 限界（config.CANDIDATE_FUNNEL_MAX_R2）。
    S004 R2：三组独立外部源用 ThreadPoolExecutor(max_workers=2) 并行采集
    （R1 genes∥board、R2 activity∥fund、R3 auction∥catalyst）。
    """
    from concurrent.futures import ThreadPoolExecutor
    from config import default_config
    as_of = datetime.now()
    phase = _fetch_sentiment_phase(date, ctx)
    eff = resolve_thresholds(cfg, phase)  # S072 STI 去噪：phase 不再调阈值（固定基数），仅记录
    current_stage = _STAGE_MAP.get(stage, "s1")
    # S084 Q1=A/Q2=B：T-1 昨日（zt_pool/derived 取昨日值；activity/fund 按 date 分路径）
    from datetime import date as _date, timedelta as _timedelta
    yesterday_date: str | None
    try:
        from vr_paths import last_trading_date as _last_td
        _d = _date.fromisoformat((date or "")[:10])
        yesterday_date = _last_td(_d - _timedelta(days=1)).isoformat()
    except Exception:
        # date 畸形不可解析 → None（zt_pool/derived 不取，不用今日值冒充 T-1，review HIGH 修复）
        yesterday_date = None
    # S084 R4.2：板块资金（行业级）—— market.get_overview() 5min 缓存
    # （防封底线：不裸调 market._sectors() raw akshare 无 em_get/circuit_breaker）
    sectors = None
    try:
        import market as _market
        sectors = (_market.get_overview() or {}).get("sectors")
    except Exception:
        sectors = None
    # S084 R2：涨停池原始 dict（T-1 昨日池，走 em_get 限流）+ 行业映射（hybk）
    from candidate_funnel.sources import zt_pool_source
    zt_pool_map = zt_pool_source.fetch_zt_pool_map(yesterday_date) if yesterday_date else {}
    # 行业映射从 zt pool hybk 提取（em_get-backed 替代 raw akshare individual_info，防封 review HIGH 修复）
    industry_map = {c: p.get("hybk") for c, p in zt_pool_map.items() if p.get("hybk")}
    max_r2 = int(getattr(default_config, "CANDIDATE_FUNNEL_MAX_R2", 80))
    base_conditions = [
        f"换手冷档={eff.turnover_cold}%",
        f"换手热档={eff.turnover_hot}%",
        f"量比活跃线={eff.vol_ratio_active}",
        f"成交额下限={eff.amount_yi_min}亿",
        f"数据阶段={current_stage}（offset=1 北向/龙虎榜缺数据标 missing 保留）",
        f"R2 top-N 限界：取前 {max_r2} 候选（按 gene_score 降序）",
    ]

    def _fetch_pair(fn_a, fn_b):
        """并行采集两个独立源，任一失败返空 dict 不阻断另一个。"""
        with ThreadPoolExecutor(max_workers=2) as ex:
            fu_a = ex.submit(fn_a)
            fu_b = ex.submit(fn_b)
            a = fu_a.result()
            b = fu_b.result()
        return a, b

    # ---- R1 宽源（并行）----
    r1_data_status: str | None = None
    r1_data_reason: str | None = None
    try:
        genes, board = _fetch_pair(
            lambda: sources.gene.fetch_genes(date),
            lambda: sources.board_ladder.fetch_board_ladder(date),
        )
    except Exception as exc:  # noqa: BLE001 — 采集失败标记层，不静默返空（S023 C2）
        genes, board = {}, {}
        r1_data_status = "未取得"
        r1_data_reason = f"R1 宽源采集失败: {exc}"
    r1_input = list(genes.keys())
    r1_kept, r1_filtered = _filter_r1(r1_input, genes)
    # S004 R3：top-N 限界——R2 采集前按 gene_score 降序取前 max_r2（R1 全量保留展示）
    r2_input_codes = _top_n_by_gene_score(r1_kept, genes, max_r2)
    r1 = FunnelLayer(
        layer_id="R1", name="宽源", as_of=as_of,
        input_count=len(r1_input), output_count=len(r1_kept),
        filtered_out=r1_filtered, output_codes=r1_kept,
        conditions=["涨停基因得分筛选", "连板梯队（含炸板/昨涨停今表现）", *base_conditions],
        passed=[
            {"code": c, "name": genes.get(c, {}).get("name", c),
             "gene_score": genes.get(c, {}).get("gene_score"),
             "consec_boards": _consec_boards_for(c, board)}
            for c in r1_kept
        ],
        data_status=r1_data_status, data_reason=r1_data_reason,
    )
    layers: list[FunnelLayer] = [r1]

    # ---- R2 收敛（并行）——S084 R1-only：活跃度过滤已下放战法层，本层仅展示全量 ----
    # S085 A4/A3：盘前所有因子取 T-1（S084 盘前边界实现缺口）——盘前 fetch_activity 用
    # yesterday_date 走 kline T-1 路径（算 prev_amount_yi/K线派生，修放量比降级 limitup_strategy:922）；
    # 历史日保 date（replay 取该日）。
    _is_pre_market = (date or "")[:10] >= _date.today().isoformat()
    act_date = (yesterday_date or date) if _is_pre_market else date
    r2_data_status: str | None = None
    r2_data_reason: str | None = None
    try:
        activity, fund = _fetch_pair(
            lambda: sources.activity.fetch_activity(r2_input_codes, act_date),
            lambda: sources.fund_flow.fetch_fund_flow(r2_input_codes, date, sectors=sectors, industry_map=industry_map),
        )
    except Exception as exc:  # noqa: BLE001 — 采集失败标记层（S023 C2）
        activity, fund = {}, {}
        r2_data_status = "未取得"
        r2_data_reason = f"R2 收敛采集失败: {exc}"
    # R1 passed 补齐 activity 字段——矩阵展示 R1-only 候选换手率/量比/成交额/振幅。
    # activity 已在 R2 采集（fetch_activity 输入=r2_input_codes top-N 限界），回填 R1 passed；
    # 超出 top-N 的候选 activity 缺失 → 这些列 None，不臆造。
    if activity:
        for _p in r1.passed:
            _a = activity.get(_p.get("code"), {}) or {}
            _p["turnover_pct"] = _a.get("turnover_pct")
            _p["vol_ratio"] = _a.get("vol_ratio")
            _p["amount_yi"] = _a.get("amount_yi")
            _p["amplitude_pct"] = _a.get("amplitude_pct")
    # S084 TASK A：R2 不再过滤活跃度——下放战法层。r2_kept = R1 全量，filtered_out 留空。
    r2_kept = list(r1_kept)
    r2_filtered: list[FilterRecord] = []
    if r2_data_status is None:
        r2_data_status = "R2 已下放战法"
        r2_data_reason = "活跃度过滤已下放战法层，本层保留 R1 全量候选（不过滤）"
    r2 = FunnelLayer(
        layer_id="R2", name="收敛", as_of=as_of,
        input_count=len(r1_kept), output_count=len(r2_kept),
        filtered_out=r2_filtered, output_codes=r2_kept,
        conditions=["R2 已下放战法（不过滤活跃度）", *base_conditions],
        passed=[
            {"code": c, "name": activity.get(c, {}).get("name", c),
             "gene_score": genes.get(c, {}).get("gene_score"),
             "consec_boards": _consec_boards_for(c, board),
             "turnover_pct": activity.get(c, {}).get("turnover_pct"),
             "vol_ratio": activity.get(c, {}).get("vol_ratio"),
             "amount_yi": activity.get(c, {}).get("amount_yi"),
             "amplitude_pct": activity.get(c, {}).get("amplitude_pct"),
             "main_net_inflow": (fund.get(c, {}) or {}).get("main_net_inflow"),
             "main_net_5d": (fund.get(c, {}) or {}).get("main_net_5d"),
             "northbound": (fund.get(c, {}) or {}).get("northbound")}
            for c in r2_kept
        ],
        data_status=r2_data_status, data_reason=r2_data_reason,
    )
    layers.append(r2)

    # ---- R3 定稿（并行）——S084 R1-only：竞价/催化过滤已下放战法层，本层仅展示全量 ----
    r3_data_status: str | None = None
    r3_data_reason: str | None = None
    try:
        auction, catalyst = _fetch_pair(
            lambda: sources.auction.fetch_auction(date),
            lambda: sources.catalyst.fetch_catalyst(r2_kept, date),
        )
    except Exception as exc:  # noqa: BLE001 — 采集失败标记层（S023 C2）
        auction, catalyst = {}, {}
        r3_data_status = "未取得"
        r3_data_reason = f"R3 定稿采集失败: {exc}"
    # S084 TASK A：R3 不再过滤竞价/催化——下放战法层。r3_kept = R2 全量（=R1），filtered_out 留空。
    # 原 exp-3 降级（auction/catalyst 均空时保留 R2）已成默认行为，不再单独标降级。
    r3_kept = list(r2_kept)
    r3_filtered: list[FilterRecord] = []
    if r3_data_status is None:
        r3_data_status = "R3 已下放战法"
        r3_data_reason = "竞价/催化过滤已下放战法层，本层保留 R2 全量候选（不过滤）"
    r3 = FunnelLayer(
        layer_id="R3", name="定稿", as_of=as_of,
        input_count=len(r2_kept), output_count=len(r3_kept),
        filtered_out=r3_filtered, output_codes=r3_kept,
        conditions=["R3 已下放战法（不过滤竞价/催化）", *base_conditions],
        passed=[
            {"code": c, "name": _resolve_name(c, genes, activity, auction, catalyst),
             "gene_score": genes.get(c, {}).get("gene_score"),
             "consec_boards": _consec_boards_for(c, board),
             "auction_open_pct": auction.get(c, {}).get("auction_open_pct"),
             "matched_triggers": _r3_triggers(c, auction, catalyst),
             "catalyst_summary": _catalyst_summary(c, catalyst)}
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

    # ---- 最终候选 = R1 全涨停 ∪ 自选（S084 R1-only：不经 R2/R3 收敛）----
    final_codes = list(dict.fromkeys(r1_kept + list(wl)))
    cards = []
    # S084 R3：derived source 懒加载（per code 取 T-1 昨日派生，盘前未采集→None 降级）
    from candidate_funnel.sources import derived_source
    for code in final_codes:
        name = (
            genes.get(code, {}).get("name")
            or activity.get(code, {}).get("name")
            or auction.get(code, {}).get("name")
            or code
        )
        ind = build_indicator_set(code, name, genes, activity, fund, auction, catalyst, board)
        # S084 Q6=B：透传 3 子对象（gene_obj/pool_item/derived）
        gene_obj = genes.get(code, {}).get("gene_obj")
        pool_item = zt_pool_map.get(code) if zt_pool_map else None
        derived = derived_source.fetch_derived(code, yesterday_date) if yesterday_date else None
        # S085 B3：seal_delta 从 derived 透传到 ind（derived_source 已并入 trajectory reader）
        if derived is not None:
            ind.seal_delta = derived.get("seal_delta")
        cards.append(build_diagnosis_card(
            code, name, ind, eff, market_ctx=board, as_of=as_of,
            gene_obj=gene_obj, pool_item=pool_item, derived=derived,
            # S085 B2：bulk 漏斗 with_seat_detail=False（默认）——席位聚合 per-code 调
            # compute_consensus_signal（3 次 datacenter/code），N 候选会拖垮响应；
            # 选股池列表跳过，单股 diagnose() 才开 with_seat_detail=True。
        ))

    # S085 B1：run 级市场聚合上下文（4 率 + lianban_stocks + date），
    # 复用 board_ladder.get_market_emotion_raw shared cache（零额外外调）。
    # 非个股字段（S049 B 已剥离三率）；仅展示/审计，不参与 capped/胜率/结算。
    market_context: dict | None = None
    try:
        from candidate_funnel.sources.board_ladder import get_market_emotion_raw
        emo = get_market_emotion_raw(date)
        if emo:
            market_context = {
                "date": emo.get("date") or date,
                "seal_rate": emo.get("seal_rate"),
                "break_rate": emo.get("break_rate"),
                "promotion_rate": emo.get("promotion_rate"),
                "max_boards": emo.get("max_boards"),
                "lianban_stocks": emo.get("lianban_stocks") or [],
            }
    except Exception:
        market_context = None

    return FunnelResult(
        run_id=f"run-{date}-{stage}",
        date=date,
        layers=layers,
        final_candidates=cards,
        threshold_config=cfg,
        sentiment_phase=phase,
        as_of=as_of,
        market_context=market_context,
    )


def diagnose(code: str, date: str, cfg: ThresholdConfig, ctx: "SentimentContext | None" = None) -> DiagnosisCard:
    """构建单只股票诊断卡（E3 GET /candidates/{code}/diagnosis 用）。

    S063 T5：可选 ctx 参数接管线头部 SentimentContext。

    S049 C1：as_of=数据源最早行日期（数据下限，比最晚保守——最晚会掩盖某源陈旧）；
    全无日期 fallback now()。
    """
    phase = _fetch_sentiment_phase(date, ctx)
    eff = resolve_thresholds(cfg, phase)
    genes = sources.gene.fetch_genes(date)
    board = sources.board_ladder.fetch_board_ladder(date)
    # S085 A4/A3：先算 yesterday_date（盘前所有因子取 T-1 用，原在 fetch_activity 后移前）
    from datetime import date as _date, timedelta as _timedelta
    yesterday_date: str | None
    try:
        from vr_paths import last_trading_date as _last_td
        _d = _date.fromisoformat((date or "")[:10])
        yesterday_date = _last_td(_d - _timedelta(days=1)).isoformat()
    except Exception:
        yesterday_date = None
    # S085 A4/A3：盘前（date>=today）fetch_activity 用 yesterday_date 走 kline T-1
    # （算 prev_amount_yi/K线派生，修放量比降级 limitup_strategy:922）；历史日保 date（replay 取该日）
    _is_pre_market = (date or "")[:10] >= _date.today().isoformat()
    act_date = (yesterday_date or date) if _is_pre_market else date
    activity = sources.activity.fetch_activity([code], act_date)
    # S084 R4.2：sectors 从 market.get_overview() 取（5min 缓存，防封）
    sectors = None
    try:
        import market as _market
        sectors = (_market.get_overview() or {}).get("sectors")
    except Exception:
        sectors = None
    # S084 R2：zt_pool_map + 行业映射（hybk，em_get-backed 替代 individual_info，防封 review HIGH 修复）
    from candidate_funnel.sources import zt_pool_source
    zt_pool_map = zt_pool_source.fetch_zt_pool_map(yesterday_date) if yesterday_date else {}
    industry_map = {c: p.get("hybk") for c, p in zt_pool_map.items() if p.get("hybk")}
    fund = sources.fund_flow.fetch_fund_flow([code], date, sectors=sectors, industry_map=industry_map)
    auction = sources.auction.fetch_auction(date)
    catalyst = sources.catalyst.fetch_catalyst([code], date)
    name = (
        genes.get(code, {}).get("name")
        or activity.get(code, {}).get("name")
        or code
    )
    # S049 C1：收集各源 _as_of 取最早（YYYY-MM-DD 字典序=日历序），无则 now()
    src_dates: list[str] = []
    for src in (activity.get(code, {}), fund.get(code, {}), auction.get(code, {}), catalyst.get(code, {})):
        d = (src or {}).get("_as_of")
        if d:
            src_dates.append(d)
    as_of = min(src_dates) if src_dates else datetime.now()
    ind = build_indicator_set(code, name, genes, activity, fund, auction, catalyst, board)
    # S084 Q6=B：透传 3 子对象（zt_pool_map 已采集复用；derived guard yesterday_date）
    from candidate_funnel.sources import derived_source
    gene_obj = genes.get(code, {}).get("gene_obj")
    pool_item = zt_pool_map.get(code)
    derived = derived_source.fetch_derived(code, yesterday_date) if yesterday_date else None
    return build_diagnosis_card(
        code, name, ind, eff, market_ctx=board, as_of=as_of,
        gene_obj=gene_obj, pool_item=pool_item, derived=derived,
        trade_date=yesterday_date,  # S085 B2：单股 diagnose 开席位聚合（1 code 开销可接受）
        with_seat_detail=True,
    )
