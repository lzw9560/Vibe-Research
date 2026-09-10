# -*- coding: utf-8 -*-
"""S181 趋势波段臂（B 臂）signal generator——板块周期 phase + 资金流净流入 composite。

spec: specs/S181-trend-band-arm/spec.md
plan: specs/S181-trend-band-arm/plan.md

非纯价格动量（避 §44 falsified）：primary=板块 rotation phase（启动/发酵）+
资金净流入 composite；secondary=板块成分股 sector_rank。不调 run_non_limitup_funnel
/ score_candidates（§44 falsified 4 因子 relative_strength/ma_bullish/volume_signal
/sector_strength）——只用 build_non_limitup_candidates 取成分股 + 资金流筛。

Deferred：zt 动量分量（S182）、新闻/政策催化剂（S183）——本骨架不含。
§44 harness（板块级 rotation 信号验证）另 spec，不在此范围。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_LOGGER = logging.getLogger("vibe-research")

#: swing trade 参数（§44 未验 paper params，spec R5）。
TREND_STOP_PCT: float = -6.0       # 止损 -6%（swing 容忍更大回撤 vs breakout -4%）
TREND_TAKE_PCT: float = 15.0       # 止盈 +15%（swing 目标更大 vs breakout +8%）
TREND_MAX_HOLD: int = 10           # 最大持仓 10 交易日（2 周 vs breakout 3 天）
TREND_TOP_N: int = 5               # 每日选 top N 候选
TREND_TOP_SECTORS: int = 5         # trending sectors 上限


def _identify_trending_sectors(date: str) -> list[dict]:
    """板块周期 phase + 资金流净流入 composite → top trending sectors（非 zt 动量）。

    1. sector_cycle.aggregate_sectors(date) → 板块涨停聚合
    2. classify_phase → phase + modifier（启动 1.1 / 发酵 1.0）
    3. market._sectors() → 行业资金净流入（亿）
    4. composite = phase_modifier × fund_flow_weight（不含 zt_momentum）
    5. filter phase ∈ {启动, 发酵} → rank by composite desc → top TREND_TOP_SECTORS
    """
    from strategies.sector_cycle import aggregate_sectors, classify_phase  # noqa: PLC0415

    sectors = aggregate_sectors(date)
    if not sectors:
        return []

    # 资金流 → {industry_name: net(亿)}（东财行业板块，与 baostock 行业名可能不完全匹配）
    flow_map: dict[str, float] = {}
    try:
        import market  # noqa: PLC0415
        for s in market._sectors():
            flow_map[str(s.get("name", ""))] = float(s.get("net", 0) or 0)
    except Exception:
        flow_map = {}

    trending: list[dict] = []
    for s in sectors:
        ind = s.get("industry", "")
        zt_today = s.get("zt_count_today", 0)
        zt_mom = s.get("zt_momentum", 0)
        avg_3d = zt_today - zt_mom  # 从 zt_momentum 反推 avg_3d
        has_history = avg_3d > 0 or zt_today > 0
        phase, modifier, note = classify_phase(zt_today, avg_3d, has_history)
        if phase not in ("启动", "发酵"):
            continue
        net = flow_map.get(ind)
        if net is None:
            fund_weight = 1.0          # 板块名不匹配 → 中性不排除
        elif net > 0:
            fund_weight = 1.0 + min(net / 10.0, 1.0)  # 净流入加分（上限 +1.0）
        else:
            fund_weight = 0.5          # 净流出降权不排除
        composite = round(modifier * fund_weight, 3)
        trending.append({
            "industry": ind, "phase": phase, "modifier": modifier,
            "zt_count_today": zt_today, "fund_flow_net": net,
            "composite_score": composite, "phase_note": note,
        })

    trending.sort(key=lambda x: x["composite_score"], reverse=True)
    for i, s in enumerate(trending[:TREND_TOP_SECTORS]):
        s["rank"] = i + 1
    return trending[:TREND_TOP_SECTORS]


def select_trend_candidates(date: str | None = None) -> list[dict]:
    """趋势波段候选选股（复用 build_non_limitup_candidates，不用 §44 falsified 分量）。

    1. _identify_trending_sectors(date) → top 5 trending sectors
    2. build_non_limitup_candidates → 板块成分股 + sector_rank（不调 score_candidates）
    3. tradability 过滤（ST/退市/创业板/科创板/北交所排除，同 gather 口径）
    4. sector_rank 升序（1=最强）→ top TREND_TOP_N

    返回 [{code, name, sector, sector_rank, close, pattern, strategy_score}]。
    pattern=None（不跑 §44 falsified 形态扫描）；strategy_score=板块 composite。
    """
    from strategies.pattern_scan import load_industry_map  # noqa: PLC0415
    from strategies.market_scan import build_non_limitup_candidates  # noqa: PLC0415
    from strategies.first_board_filter import _get_kline_cache  # noqa: PLC0415

    if date is None:
        from vr_paths import prev_trading_date_str  # noqa: PLC0415
        date = prev_trading_date_str()

    top = _identify_trending_sectors(date)
    if not top:
        return []

    industry_map = load_industry_map()
    cache = _get_kline_cache()
    candidates = build_non_limitup_candidates(top, industry_map, cache, per_sector=20)

    # tradability 过滤（非 §44 因子，实用交易约束）
    try:
        from candidate_funnel.sources._filters import classify_tradability  # noqa: PLC0415
        from candidate_funnel.sources.st_play_radar import load_st_play_radar  # noqa: PLC0415
        radar = load_st_play_radar()
        kept: list[dict] = []
        for c in candidates:
            keep, _reason, st_play = classify_tradability(
                c.get("name", ""), str(c.get("code", "")), radar)
            if keep:
                kept.append({**c, "st_play": st_play} if st_play else c)
        candidates = kept
    except Exception:
        pass  # tradability 不可用 → 不过滤（降级不阻塞）

    score_map = {s["industry"]: s["composite_score"] for s in top}
    candidates.sort(key=lambda c: c.get("sector_rank") or 999)
    return [
        {
            "code": c.get("code", ""), "name": c.get("name", ""),
            "sector": c.get("sector", ""), "sector_rank": c.get("sector_rank"),
            "close": c.get("close"), "pattern": None,
            "strategy_score": score_map.get(c.get("sector", "")),
        }
        for c in candidates[:TREND_TOP_N]
    ]


def trend_arm_status(journal) -> dict:
    """趋势波段臂状态（读 trade_journal，仿 index_replication_floor.hold_status）。

    journal: TradeJournal 实例。返 {arm, n_total, n_realized, n_unrealized,
    total_net_pnl, winrate, avg_cost_pct, honest_label}。
    """
    records = journal.query_records(arm="trend", is_dead_arm=None)
    realized = [r for r in records if r.is_realized == 1]
    unrealized = [r for r in records if r.is_realized == 0]
    wins = [r for r in realized if r.net_pnl is not None and r.net_pnl > 0]
    total_net = sum(float(r.net_pnl) for r in realized if r.net_pnl is not None)
    total_cost = sum(float(r.cost_pct) for r in realized if r.cost_pct)
    n_realized = len(realized)
    return {
        "arm": "trend",
        "n_total": len(records),
        "n_realized": n_realized,
        "n_unrealized": len(unrealized),
        "total_net_pnl": round(total_net, 2),
        "winrate": round(len(wins) / n_realized * 100, 1) if n_realized else 0.0,
        "avg_cost_pct": round(total_cost / n_realized, 2) if n_realized else 0.0,
        "honest_label": "exploratory",
    }


def trend_arm_report(journal) -> dict:
    """趋势波段臂报告（状态 + 聚合统计 + 参数 + 风险提醒，仿 weekly_report）。"""
    status = trend_arm_status(journal)
    try:
        agg = journal.aggregate_by_arm().get("trend", {})
    except Exception:
        agg = {}
    return {
        **status,
        "aggregate_stats": agg,
        "params": {
            "stop_pct": TREND_STOP_PCT, "take_profit_pct": TREND_TAKE_PCT,
            "max_hold_days": TREND_MAX_HOLD, "top_n": TREND_TOP_N,
        },
        "note": "题材/政策趋势驱动（非纯动量），§44 未验证；paper tracking 不推荐真金",
        "risk_disclaimer": "历史统计特征，市场有风险",
    }


if __name__ == "__main__":
    import argparse
    import json

    p = argparse.ArgumentParser(description="S181 趋势波段臂 signal generator")
    sub = p.add_subparsers(dest="cmd")
    sub_sel = sub.add_parser("select", help="选趋势波段候选")
    sub_sel.add_argument("--date", default=None)
    sub.add_parser("status", help="查看趋势臂状态")
    sub.add_parser("report", help="产出趋势臂报告")
    args = p.parse_args()

    if args.cmd == "select":
        print(json.dumps(select_trend_candidates(args.date), ensure_ascii=False, indent=2))
    elif args.cmd in ("status", "report"):
        from engine.trade_journal import TradeJournal  # noqa: PLC0415
        tj = TradeJournal()
        fn = trend_arm_status if args.cmd == "status" else trend_arm_report
        print(json.dumps(fn(tj), ensure_ascii=False, indent=2))
    else:
        p.print_help()
