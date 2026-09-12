#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T6.1+T6.2 实测：F3 融合整体 §44 event edge verdict + multifactor null 对账。

用 s44_verifier.verify(edge_type='event')：
- returns = 1092 条交易的 gross_return（% 收益，verify 按 round_trip_cost 算 materiality floor）；
- dates = entry_date（per-pick 对齐——必须传，days_robust 用 day-clustered n 非 pooled 1092，防 §44v1 inflate）；
- edge_type='event'（不用 selection——spec grill CRITICAL#2 survivors 不可复现；event edge 测群体收益 lift）；
- pass 门 = status=='robust_edge'（event edge 无 selection_lift，spec §5 A6「2x lift」与 event edge 矛盾，dep map 确认）。

⚠️ Phase 3a 代理局限：R4 融合层未建，F3 用现有真实交易（breakout arm 为主）的收益当"融合 event"代理
——测的是"系统当前交易有无 event edge"，非"FS2 加权融合的 event edge"。Phase 3b R4 建后用真
FS2 加权融合 event 收益复跑。breakout 是 §44 证否弱信号（胜率 33.4%），预期 F3 falsified/underpowered，
与 multifactor null 一致。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from s44_verifier import verify  # noqa: E402
from engine.trade_journal import TradeJournal  # noqa: E402
from tools.f3_verdict import interpret_f3_verdict  # noqa: E402

ROUND_TRIP_COST = 0.007  # 0.7% 往返成本（A 股印花+佣金+滑点近似）


def main() -> None:
    tj = TradeJournal()
    cases = tj.query_records(is_realized=1, is_dead_arm=0, limit=10000)

    returns: list[float] = []
    dates: list[str] = []
    for rec in cases:
        gr = rec.gross_return
        if gr is None:
            continue
        returns.append(float(gr))
        dates.append(rec.entry_date)

    print(f"# F3 event edge: {len(returns)} 条融合 event（realized 交易 gross_return）, {len(set(dates))} 唯一日", file=sys.stderr)
    if len(returns) < 30:
        print(f"# 样本不足（{len(returns)}<30），无法跑 §44", file=sys.stderr)
        return

    v = verify(
        returns=returns,
        n_trials=1,
        edge_type="event",
        dates=dates,
        round_trip_cost=ROUND_TRIP_COST,
        frozen_commit="S194-F3-dev",
        n_comparisons=1,
    )

    em = getattr(v, "event_metrics", None)
    day_mean = getattr(em, "day_mean", None) if em else None
    interp = interpret_f3_verdict(
        status=v.status,
        event_status=getattr(v, "event_status", None),
        day_mean=day_mean,
        days_robust=v.days_robust,
        p_bh=getattr(v, "p_bh", None),
    )

    print(f"\n=== S194 F3 融合整体 §44 event edge ===")
    print(f"  status: {v.status}  event_status: {getattr(v, 'event_status', None)}")
    print(f"  day_mean: {day_mean}  days_robust: {v.days_robust}  p_bh: {getattr(v, 'p_bh', None)}")
    print(f"  n: {v.n}  n_effective(day-clustered): {getattr(v, 'n_effective', None)}")
    print(f"  round_trip_cost: {ROUND_TRIP_COST}（进 materiality floor max(0.003, cost×0.5)）")
    print(f"\n  fusion_conclusion: {interp['fusion_conclusion']}")
    print(f"  null_engagement: {interp['null_engagement']}")


if __name__ == "__main__":
    main()
