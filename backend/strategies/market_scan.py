# -*- coding: utf-8 -*-
"""S094 market_scan 因子层 + 形态子 + 领涨子（spec §3.M 定稿）。

模块归属定稿（grill 第 2 轮）：本模块是 market_scan pipeline 的因子层 + 形态子 +
领涨子单一事实源；non_limitup_funnel.py 保留 run_non_limitup_funnel 瘦身为
"调本模块产候选"的入口（T9/R27 拆打分后）。

S2 落地：
- T7 板块领涨子 compute_sector_stock_rank / compute_sector_stock_rank_map（板块内个股
  relative_strength 降序排名，spec R11）。
- T8 候选生产 build_non_limitup_candidates（统一 shape {code,name,bars,sector,
  sector_rank,close}，spec R14；name 从 code_industry 反查，sector_rank=板块内 T7）。
  S3 R26 gather_non_limitup_candidates(date) 会在此外包 sector_rotation。

后续形态子/因子装配按 S3 R10 等任务扩入。零 em_get：纯本地 bars 计算（code_industry
name 反查为本地 DB，非东财）。
"""
from __future__ import annotations

from strategies.pattern_scan import PatternScan, _compute_ma, compute_relative_strength, get_sector_stocks


def compute_sector_stock_rank_map(
    sector_stocks: list[str],
    bars_map: dict[str, list[dict]],
    days: int = 5,
) -> dict[str, int]:
    """板块内全部成分股的 relative_strength 降序排名表（spec R11 批量版，领涨子）。

    返回 {code: rank}（1=最强，降序）。5 日涨幅 None（数据不足）的股票不入表
    （诚实降级，不臆造名次）。与 sector_cycle.sector_strength_rank（板块间）不同——
    本函数是板块内个股排名，供 dragon_head.match 读 market_scan_ctx.sector_rank
    （板块内≤3 命中，R9）。

    口径：板块内 sector_ret 对所有成分股是恒定偏移，故相对强度排名 ≡ 绝对 5 日
    涨幅排名（精确同序，非近似）。用 compute_relative_strength(sb, None, days)
    取个股 5 日涨幅（其 sector_bars=None 分支即返个股涨幅，pattern_scan 既定语义），
    免去重复聚合板块等权日K（聚合逻辑留 non_limitup_funnel._aggregate_sector_bars，
    T9 统一搬家时再迁入本模块）。
    """
    if not sector_stocks:
        return {}
    scored: list[tuple[str, float]] = []
    for s in sector_stocks:
        sb = bars_map.get(s) or []
        ret = compute_relative_strength(sb, None, days)
        if ret is not None:
            scored.append((s, ret))
    scored.sort(key=lambda x: x[1], reverse=True)
    return {s: rank for rank, (s, _ret) in enumerate(scored, start=1)}


def compute_sector_stock_rank(
    code: str,
    sector_stocks: list[str],
    bars_map: dict[str, list[dict]],
    days: int = 5,
) -> int | None:
    """板块内个股 relative_strength 降序排名（spec R11，领涨子）。

    返回 code 在 sector_stocks 内的排名（1=最强）；code 不在成分股 / 自身数据不足
    （5 日涨幅 None）→ 返 None（诚实降级，不臆造名次）。委托 compute_sector_stock_rank_map
    取批量排名表查 code。
    """
    if not sector_stocks or code not in sector_stocks:
        return None
    return compute_sector_stock_rank_map(sector_stocks, bars_map, days).get(code)


def _load_code_names(codes: list[str]) -> dict[str, str]:
    """T8：批量从 code_industry 表反查 code→name（spec R14 N6，kline cache FIELDS 无 name）。

    code_industry(code, name, industry, updated_at) 表有 name 列（tools/backfill_industry 实锤）。
    DB 不存在 / 表缺失 / 查询异常 → 返空 dict（诚实降级，不臆造名）。
    """
    codes = [c for c in codes if c]
    if not codes:
        return {}
    try:
        import sqlite3
        from vr_paths import resolve_data_dir
        db = resolve_data_dir() / "gene_scores.db"
        if not db.exists():
            return {}
        conn = sqlite3.connect(str(db), timeout=5)
        try:
            placeholders = ",".join("?" * len(codes))
            rows = conn.execute(
                f"SELECT code, name FROM code_industry WHERE code IN ({placeholders})",
                codes,
            ).fetchall()
            return {r[0]: r[1] for r in rows if r[1]}
        finally:
            conn.close()
    except Exception:
        return {}


def build_non_limitup_candidates(
    top: list[dict],
    industry_map: dict[str, str],
    cache: dict[str, list[dict]],
    per_sector: int = 20,
) -> list[dict]:
    """T8：产非涨停候选（统一 shape {code,name,bars,sector,sector_rank,close}，spec R14）。

    top: sector_rotation 的 strength_rank 项 [{industry, zt_count_today, rank, ...}]（含板块间 rank）。
    industry_map: {code: industry}（load_industry_map）。
    cache: baostock_kline_cache {code: [bars]}。
    per_sector: 每板块成分股上限（性能预算 §3.M，≤50）。

    - bars<20 跳过（既有口径，MA 自算需足够窗口）。
    - name 从 code_industry 批量反查（_load_code_names）。
    - sector_rank=板块内个股排名（compute_sector_stock_rank_map，T7，供 S3
      market_scan_ctx/dragon_head R9 板块内≤3 命中）；注意与 top[].rank（板块间）同名不同语境。
    - close=bars[-1].close。
    """
    candidates: list[dict] = []
    all_codes: list[str] = []
    sector_stocks_map: dict[str, list[str]] = {}  # ind → 板块全成分股（rank 用全成分，非采样子集）
    for s in top:
        ind = s.get("industry")
        if not ind:
            continue
        stocks = get_sector_stocks(ind, industry_map)
        sector_stocks_map[ind] = stocks
        for code in stocks[:per_sector]:
            bars = cache.get(code, [])
            if len(bars) >= 20:
                candidates.append({"code": code, "bars": bars, "sector": ind})
                all_codes.append(code)

    name_map = _load_code_names(all_codes)
    # 板块内排名（全成分，非 per_sector 采样子集）——每板块算一次
    sector_rank_intra = {
        ind: compute_sector_stock_rank_map(stocks, cache)
        for ind, stocks in sector_stocks_map.items()
    }
    for cand in candidates:
        code = cand["code"]
        ind = cand["sector"]
        bars = cand["bars"]
        cand["name"] = name_map.get(code, "")
        cand["sector_rank"] = sector_rank_intra.get(ind, {}).get(code)
        cand["close"] = bars[-1].get("close") if bars else None
    return candidates


def _build_market_data(pattern, candidate: dict) -> dict:
    """从 PatternScan + candidate 构建 check_quality_standards 所需的 market_data。

    S094 R27（2b-i-c）：从 non_limitup_funnel 迁入 market_scan（因子层 home，§3.M），
    供 score_candidates(market_scan) check_quality 闸前移用（避 strategy_funnel_registry
    ↔ non_limitup_funnel 循环 import）。S094 R1：ma5/ma10/ma20 从 bars 自算（不依赖 cache 字段）。
    pattern=None（候选无 PatternScan）→ 各 pattern 字段 getattr 返 None（check_quality 标 missing 不阻断）。
    """
    bars = candidate.get("bars") or []
    ma5 = ma10 = ma20 = None
    if bars:
        ma5 = _compute_ma(bars, 5)
        ma10 = _compute_ma(bars, 10)
        ma20 = _compute_ma(bars, 20)
    return {
        "close": candidate.get("close"),
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "vol_ratio": getattr(pattern, "volume_breakout_ratio", None),
        "amount_yi": getattr(pattern, "amount_yi", None),
        "consecutive_boards": candidate.get("consecutive_boards"),
        "consolidation_days": getattr(pattern, "consolidation_days", None),
        "vol_breakout_ratio": getattr(pattern, "volume_breakout_ratio", None),
        "sector_rank": candidate.get("sector_rank"),
        "turnover_rate": candidate.get("turnover_rate"),
        "recent_zt_days": candidate.get("recent_zt_days"),
        "t1_limit_up": candidate.get("t1_limit_up"),
    }


def gather_non_limitup_candidates(
    date: str,
    top_sectors: int = 5,
    per_sector: int = 20,
) -> dict:
    """S094 R26/T17：非涨停 pipeline 候选采集（抽自 routers/strategy.py 端点）。

    sector_rotation(date) → top 涨停板块 → load_industry_map → build_non_limitup_candidates
    → run_non_limitup_funnel（产 PatternScan factors）→ score_candidates(market_scan)。
    供 workflow._collect 产 market_scan_scored（briefing 双 pipeline 分区透传，R28）。

    返 {candidates: scored[:50], count, sectors_scanned, candidates_input}（端点同 shape）。
    无热门板块（当日无涨停板块）→ candidates 空。数据依赖 baostock_kline_cache 全 A
    扩容（T21-run 后非涨停股才有 bars≥20；未扩容前 candidates 恒空，诚实降级）。
    """
    # 懒 import 防 circular（market_scan ← non_limitup_funnel/strategy_funnel_registry 反向 import）
    from strategies.sector_cycle import sector_rotation
    from strategies.pattern_scan import load_industry_map
    from strategies.non_limitup_funnel import run_non_limitup_funnel
    from strategies.strategy_funnel_registry import score_candidates
    from strategies.first_board_filter import _get_kline_cache

    rot = sector_rotation(date)
    top = [s for s in rot.get("strength_rank", []) if s.get("zt_count_today", 0) > 0][:top_sectors]
    if not top:
        return {"candidates": [], "count": 0, "sectors_scanned": 0, "candidates_input": 0}
    industry_map = load_industry_map()
    cache = _get_kline_cache()
    candidates = build_non_limitup_candidates(top, industry_map, cache, per_sector)
    sector_rank_map = {s["industry"]: s.get("rank", 99) for s in top}  # 板块间
    produced = run_non_limitup_funnel(candidates, weather_state=None, sector_rank_map=sector_rank_map)
    scored = score_candidates(produced, None, "market_scan")
    return {
        "candidates": scored[:50],
        "count": len(scored),
        "sectors_scanned": len(top),
        "candidates_input": len(candidates),
        "note": "§44 Phase 2 未验证因子（relative_strength/ma_bullish/volume_signal/sector_strength），briefing 透传；数据本地 baostock",  # S094 audit LOW: 加 note 对齐端点 shape
    }
